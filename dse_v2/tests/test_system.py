#!/usr/bin/env python3

import sys
from pathlib import Path

def test_imports():
    print("Testing imports...")
    
    try:
        import numpy as np
        print(f"  ✓ numpy {np.__version__}")
    except ImportError as e:
        print(f"  ✗ numpy: {e}")
        return False
    
    try:
        import pandas as pd
        print(f"  ✓ pandas {pd.__version__}")
    except ImportError as e:
        print(f"  ✗ pandas: {e}")
        return False
    
    try:
        import torch
        print(f"  ✓ torch {torch.__version__}")
    except ImportError as e:
        print(f"  ✗ torch: {e}")
        return False
    
    try:
        import botorch
        print(f"  ✓ botorch {botorch.__version__}")
    except ImportError as e:
        print(f"  ✗ botorch: {e}")
        return False
    
    try:
        import ax
        print(f"  ✓ ax {ax.__version__}")
    except ImportError as e:
        print(f"  ✗ ax: {e}")
        return False
    
    return True

def test_project_structure():
    print("\nTesting project structure...")
    
    required_dirs = [
        'workloads',
        'design_space',
        'models',
        'optimization',
        'results',
        'scripts',
    ]
    
    all_exist = True
    for dir_name in required_dirs:
        dir_path = Path(dir_name)
        if dir_path.exists():
            print(f"  ✓ {dir_name}/")
        else:
            print(f"  ✗ {dir_name}/ (missing)")
            all_exist = False
    
    return all_exist

def test_fast_model():
    print("\nTesting fast performance model...")
    
    try:
        sys.path.append(str(Path.cwd()))
        from models.fast.performance_model import FastPerformanceModel
        
        fpga_specs = {
            'peak_gflops': 1300,
            'memory_bw_gbs': 77,
            'pcie_bw_gbs': 16,
            'bram_kb': 34000,
            'dsp_count': 12288,
        }
        
        model = FastPerformanceModel(fpga_specs)
        
        design_point = {
            'pipeline_depth': 4,
            'parallel_units': 4,
            'dataflow_pattern': 'streaming',
            'tile_npw': 1024,
            'tile_nkb': 64,
            'tile_m': 16,
            'intermediate_buffer_kb': 256,
        }
        
        workload = {'npw': 2945, 'nkb': 144, 'm': 16}
        
        result = model.evaluate_design_point(design_point, workload)
        
        print(f"  ✓ Model evaluation successful")
        print(f"    Time: {result['time_s']*1000:.2f} ms")
        print(f"    Energy: {result['energy_j']:.2f} J")
        print(f"    Feasible: {result['feasible']}")
        
        return True
    except Exception as e:
        print(f"  ✗ Model test failed: {e}")
        return False

def main():
    print("=" * 60)
    print("DSE v2 System Test")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Project Structure", test_project_structure),
        ("Fast Performance Model", test_fast_model),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    all_passed = True
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
        if not result:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("\n✅ All tests passed! System is ready.")
        return 0
    else:
        print("\n❌ Some tests failed. Please fix issues before proceeding.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
