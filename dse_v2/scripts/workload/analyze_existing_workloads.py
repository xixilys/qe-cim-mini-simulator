#!/usr/bin/env python3

import sys
from pathlib import Path
import json
import pandas as pd

def analyze_existing_workloads():
    base_dir = Path(__file__).resolve().parents[3]
    trace_dir = base_dir / 'docs/benchmarks/results/qe_workload_revalidation'
    
    if not trace_dir.exists():
        print(f"❌ Trace directory not found: {trace_dir}")
        return
    
    print("📊 Analyzing existing workload traces...")
    
    workloads = []
    
    for case_dir in trace_dir.iterdir():
        if not case_dir.is_dir():
            continue
        
        case_name = case_dir.name
        summary_file = case_dir / 'summary.json'
        
        if summary_file.exists():
            with open(summary_file) as f:
                summary = json.load(f)
            
            workload = {
                'case_name': case_name,
                'material': case_name.split('_')[0],
                'atoms': summary.get('natoms', 'unknown'),
                'functional': summary.get('functional', 'unknown'),
                'pseudo': summary.get('pseudopotential', 'unknown'),
                'solver': summary.get('dominant_solver', 'unknown'),
                'avg_npw': summary.get('avg_npw', 0),
                'avg_nkb': summary.get('avg_nkb', 0),
                'avg_m': summary.get('avg_m', 0),
                'total_time_s': summary.get('total_time_s', 0),
            }
            
            workloads.append(workload)
            print(f"  ✓ {case_name}")
    
    df = pd.DataFrame(workloads)
    
    output_dir = Path('workloads/analysis')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / 'existing_workloads_analysis.csv'
    df.to_csv(output_file, index=False)
    
    print(f"\n📈 Statistics:")
    print(f"  Total workloads: {len(df)}")
    print(f"  Materials: {df['material'].nunique()}")
    print(f"  Solver types: {df['solver'].unique()}")
    print(f"  npw range: {df['avg_npw'].min():.0f} - {df['avg_npw'].max():.0f}")
    print(f"  nkb range: {df['avg_nkb'].min():.0f} - {df['avg_nkb'].max():.0f}")
    
    print(f"\n✅ Analysis saved to {output_file}")
    
    print("\n🎯 Suggested new workload types:")
    materials = set(df['material'].unique())
    suggestions = [
        ('GaN', 'Semiconductor material'),
        ('MoS2', '2D material'),
        ('TiO2', 'Transition metal oxide'),
    ]
    
    for material, category in suggestions:
        if material not in materials:
            print(f"  - {material} ({category})")

if __name__ == '__main__':
    analyze_existing_workloads()
