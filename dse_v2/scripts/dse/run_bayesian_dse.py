#!/usr/bin/env python3

import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Tuple

import torch
from ax.service.ax_client import AxClient
from ax.service.utils.instantiation import ObjectiveProperties

sys.path.append(str(Path(__file__).resolve().parents[2]))
from models.fast.performance_model import FastPerformanceModel

class BayesianDSE:
    
    def __init__(self, design_space_path: Path, fpga_specs: Dict):
        with open(design_space_path) as f:
            self.design_space = json.load(f)
        
        self.fast_model = FastPerformanceModel(fpga_specs)
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
            name="host_fpga_dse_v2",
            parameters=parameters,
            objectives={
                "time_s": ObjectiveProperties(minimize=True),
                "energy_j": ObjectiveProperties(minimize=True),
            },
            outcome_constraints=[
                "dsp_utilization <= 0.85",
                "bram_utilization <= 0.85",
            ],
        )
    
    def evaluate_design_point(self, parameters: Dict, workload: Dict) -> Dict[str, Tuple[float, float]]:
        result = self.fast_model.evaluate_design_point(parameters, workload)
        
        self.evaluation_history.append({
            'parameters': parameters,
            'result': result,
        })
        
        return {
            'time_s': (result['time_s'], 0.0),
            'energy_j': (result['energy_j'], 0.0),
            'dsp_utilization': (result['area']['dsp_utilization'], 0.0),
            'bram_utilization': (result['area']['bram_utilization'], 0.0),
        }
    
    def run_optimization(self, workload: Dict, n_iterations: int = 50) -> pd.DataFrame:
        print(f"🚀 Starting Bayesian Optimization for {n_iterations} iterations...")
        print(f"📊 Workload: npw={workload['npw']}, nkb={workload['nkb']}, m={workload['m']}")
        
        for i in range(n_iterations):
            parameters, trial_index = self.ax_client.get_next_trial()
            result = self.evaluate_design_point(parameters, workload)
            self.ax_client.complete_trial(trial_index=trial_index, raw_data=result)
            
            if (i + 1) % 10 == 0:
                try:
                    best_params, best_values = self.ax_client.get_best_parameters()
                    print(f"Iteration {i+1}/{n_iterations}")
                    print(f"  Best time: {best_values[0]['time_s']:.4f} s")
                    print(f"  Best energy: {best_values[0]['energy_j']:.2f} J")
                except Exception as e:
                    print(f"Iteration {i+1}/{n_iterations} - Still exploring...")
        
        # Get Pareto frontier
        try:
            pareto_results = self.ax_client.get_pareto_optimal_parameters()
            
            results = []
            for arm_name, (params, values) in pareto_results.items():
                row = params.copy()
                row.update(values[0])
                row['arm_name'] = arm_name
                results.append(row)
            
            df_results = pd.DataFrame(results)
        except Exception as e:
            print(f"⚠️  Could not extract Pareto frontier: {e}")
            print("Returning all trials instead...")
            
            # Fallback: return all trials
            trials_df = self.ax_client.get_trials_data_frame()
            df_results = trials_df
        
        return df_results
    
    def save_results(self, df_results: pd.DataFrame, output_path: Path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df_results.to_csv(output_path, index=False)
        print(f"\n✅ Results saved to {output_path}")
        print(f"📈 Pareto frontier size: {len(df_results)}")
        
        # Also save all trials from evaluation history
        if self.evaluation_history:
            all_trials_path = output_path.parent / 'all_trials_v2.csv'
            df_all = pd.DataFrame(self.evaluation_history)
            df_all.to_csv(all_trials_path, index=False)
            print(f"✅ All trials saved to {all_trials_path}")
            print(f"📊 Total trials: {len(df_all)}")

def main():
    fpga_specs = {
        'peak_gflops': 1300,
        'memory_bw_gbs': 77,
        'pcie_bw_gbs': 16,
        'bram_kb': 34000,
        'dsp_count': 12288,
    }
    
    design_space_path = Path('design_space/definitions/host_fpga_design_space_v2.json')
    
    if not design_space_path.exists():
        print(f"❌ Design space not found: {design_space_path}")
        print("Run: python3 scripts/setup/define_design_space.py")
        return
    
    dse = BayesianDSE(design_space_path, fpga_specs)
    
    workload = {
        'npw': 2945,
        'nkb': 144,
        'm': 16,
    }
    
    results = dse.run_optimization(workload, n_iterations=50)
    
    output_path = Path('results/pareto/bayesian_dse_results_v2.csv')
    dse.save_results(results, output_path)

if __name__ == '__main__':
    main()
