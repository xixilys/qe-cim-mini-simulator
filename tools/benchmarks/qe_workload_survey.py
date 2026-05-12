#!/usr/bin/env python3
"""
Quick survey of all QE workload cases to identify representative samples
"""

import json
import re
from pathlib import Path
from collections import defaultdict

WORKLOAD_DIR = Path('/Volumes/remote/phd/year_2/project/dft加速/docs/benchmarks/archive/results/qe_workload_revalidation')

def extract_case_info(case_dir: Path) -> dict:
    """Extract key characteristics from a case"""
    info = {
        'name': case_dir.name,
        'duration_sec': 0,
        'nat': 0,
        'nbnd': 0,
        'kpoints': 0,
        'npw': 0,
        'fft_grid': (0, 0, 0),
        'pseudo_type': 'unknown',
        'functional': 'unknown',
        'subspace_calls': 0,
        'hpsi_calls': 0,
    }
    
    # Read metadata
    metadata_path = case_dir / 'metadata.json'
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)
            info['duration_sec'] = metadata.get('duration_sec', 0)
    
    # Read stdout
    stdout_path = case_dir / 'stdout.out'
    if stdout_path.exists():
        with open(stdout_path, errors='ignore') as f:
            text = f.read()
            
            # Extract nat
            nat_match = re.search(r'number of atoms/cell\s*=\s*(\d+)', text)
            if nat_match:
                info['nat'] = int(nat_match.group(1))
            
            # Extract nbnd
            nbnd_match = re.search(r'number of Kohn-Sham states\s*=\s*(\d+)', text)
            if nbnd_match:
                info['nbnd'] = int(nbnd_match.group(1))
            
            # Extract kpoints
            k_match = re.search(r'number of k points=\s*(\d+)', text)
            if k_match:
                info['kpoints'] = int(k_match.group(1))
            
            # Extract npw
            npw_match = re.search(r'Sum\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+)', text)
            if npw_match:
                info['npw'] = int(npw_match.group(1))
            
            # Extract FFT grid
            fft_match = re.search(r'Dense\s+grid:\s*(\d+) G-vectors\s+FFT dimensions:\s*\(\s*(\d+),\s*(\d+),\s*(\d+)\)', text)
            if fft_match:
                info['fft_grid'] = (int(fft_match.group(2)), int(fft_match.group(3)), int(fft_match.group(4)))
    
    # Infer pseudo type and functional from name
    name_lower = case_dir.name.lower()
    if '_nc' in name_lower:
        info['pseudo_type'] = 'NC'
    elif '_uspp' in name_lower:
        info['pseudo_type'] = 'USPP'
    elif '_paw' in name_lower:
        info['pseudo_type'] = 'PAW'
    
    if '_pbe0' in name_lower:
        info['functional'] = 'PBE0'
    elif '_pbe' in name_lower:
        info['functional'] = 'PBE'
    
    # Count trace calls
    subspace_trace = case_dir / 'subspace_trace.csv'
    if subspace_trace.exists():
        with open(subspace_trace) as f:
            info['subspace_calls'] = sum(1 for _ in f) - 1  # -1 for header
    
    hpsi_trace = case_dir / 'hpsi_trace.csv'
    if hpsi_trace.exists():
        with open(hpsi_trace) as f:
            info['hpsi_calls'] = sum(1 for _ in f) - 1
    
    return info

def classify_case(info: dict) -> dict:
    """Classify case by size and type"""
    classification = {}
    
    # Size classification
    if info['nat'] <= 4:
        classification['size'] = 'tiny'
    elif info['nat'] <= 10:
        classification['size'] = 'small'
    elif info['nat'] <= 50:
        classification['size'] = 'medium'
    else:
        classification['size'] = 'large'
    
    # Material type
    name = info['name'].lower()
    if 'h2' in name:
        classification['material_type'] = 'molecule'
    elif 'benzene' in name:
        classification['material_type'] = 'molecule'
    elif 'graphene' in name:
        classification['material_type'] = '2D_material'
    elif 'slab' in name:
        classification['material_type'] = 'surface'
    elif 'si' in name or 'bn' in name or 'sic' in name:
        classification['material_type'] = 'bulk_semiconductor'
    elif 'au' in name:
        classification['material_type'] = 'metal'
    else:
        classification['material_type'] = 'unknown'
    
    # Computational complexity
    if info['kpoints'] > 5:
        classification['k_complexity'] = 'high'
    elif info['kpoints'] > 1:
        classification['k_complexity'] = 'medium'
    else:
        classification['k_complexity'] = 'low'
    
    # Subspace call intensity
    if info['subspace_calls'] > 200:
        classification['subspace_intensity'] = 'very_high'
    elif info['subspace_calls'] > 50:
        classification['subspace_intensity'] = 'high'
    elif info['subspace_calls'] > 20:
        classification['subspace_intensity'] = 'medium'
    else:
        classification['subspace_intensity'] = 'low'
    
    return classification

def main():
    cases = []
    for case_dir in sorted(WORKLOAD_DIR.iterdir()):
        if case_dir.is_dir() and not case_dir.name.startswith('.'):
            info = extract_case_info(case_dir)
            classification = classify_case(info)
            cases.append({**info, **classification})
    
    # Print table
    print("=" * 150)
    print(f"{'Case':<25} {'Size':<8} {'Type':<20} {'Pseudo':<8} {'Func':<8} {'nat':<5} {'nbnd':<6} {'kpts':<5} {'npw':<7} {'Sub':<5} {'hpsi':<5} {'Dur(s)':<7}")
    print("=" * 150)
    
    for case in cases:
        print(f"{case['name']:<25} "
              f"{case['size']:<8} "
              f"{case['material_type']:<20} "
              f"{case['pseudo_type']:<8} "
              f"{case['functional']:<8} "
              f"{case['nat']:<5} "
              f"{case['nbnd']:<6} "
              f"{case['kpoints']:<5} "
              f"{case['npw']:<7} "
              f"{case['subspace_calls']:<5} "
              f"{case['hpsi_calls']:<5} "
              f"{case['duration_sec']:<7.2f}")
    
    print("=" * 150)
    print("\n## Recommended Representative Cases:\n")
    
    # Select representative cases
    selected = []
    
    # 1. Tiny molecule (baseline)
    tiny_mol = [c for c in cases if c['size'] == 'tiny' and c['material_type'] == 'molecule']
    if tiny_mol:
        selected.append(('h2_tiny', 'Tiny molecule baseline'))
    
    # 2. Small bulk with different pseudo types
    small_bulk = [c for c in cases if c['size'] == 'small' and c['material_type'] == 'bulk_semiconductor']
    if small_bulk:
        # Get one NC and one USPP
        nc_case = [c for c in small_bulk if c['pseudo_type'] == 'NC']
        uspp_case = [c for c in small_bulk if c['pseudo_type'] == 'USPP']
        if nc_case:
            selected.append((nc_case[0]['name'], 'Small bulk with NC (norm-conserving)'))
        if uspp_case:
            selected.append((uspp_case[0]['name'], 'Small bulk with USPP (ultrasoft)'))
    
    # 3. 2D material with high k-points
    graphene = [c for c in cases if 'graphene' in c['name'].lower()]
    if graphene:
        # Prefer USPP over PAW for now
        uspp_graphene = [c for c in graphene if c['pseudo_type'] == 'USPP']
        if uspp_graphene:
            selected.append((uspp_graphene[0]['name'], '2D material with high k-points (12)'))
    
    # 4. Medium bulk with high subspace intensity
    medium_high = [c for c in cases if c['size'] == 'medium' and c['subspace_intensity'] in ['high', 'very_high']]
    if medium_high:
        selected.append((medium_high[0]['name'], 'Medium bulk with high subspace intensity'))
    
    # 5. Large system (if available)
    large = [c for c in cases if c['size'] == 'large' or c['nat'] > 30]
    if large:
        selected.append((large[0]['name'], 'Large system (stress test)'))
    
    # 6. Hybrid functional (if available)
    hybrid = [c for c in cases if c['functional'] == 'PBE0']
    if hybrid:
        selected.append((hybrid[0]['name'], 'Hybrid functional (PBE0)'))
    
    for i, (name, reason) in enumerate(selected, 1):
        print(f"{i}. **{name}**: {reason}")
    
    print(f"\nTotal: {len(selected)} representative cases selected from {len(cases)} available cases")
    
    # Save to JSON
    output = {
        'all_cases': cases,
        'selected_cases': [name for name, _ in selected],
        'selection_reasoning': {name: reason for name, reason in selected}
    }
    
    output_path = Path('/tmp/qe_workload_survey.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nDetailed data saved to: {output_path}")

if __name__ == '__main__':
    main()
