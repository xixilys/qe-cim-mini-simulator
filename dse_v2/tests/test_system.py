#!/usr/bin/env python3

import importlib
import importlib.metadata
import sys
import warnings
from pathlib import Path

import pytest

REQUIRED_IMPORTS = [
    ("numpy", "numpy", "numpy"),
    ("pandas", "pandas", "pandas"),
    ("scipy", "scipy", "scipy"),
    ("torch", "torch", "torch"),
    ("botorch", "botorch", "botorch"),
    ("ax-platform", "ax", "ax-platform"),
    ("gpytorch", "gpytorch", "gpytorch"),
    ("matplotlib", "matplotlib", "matplotlib"),
    ("seaborn", "seaborn", "seaborn"),
    ("plotly", "plotly", "plotly"),
    ("wandb", "wandb", "wandb"),
    ("pyyaml", "yaml", "pyyaml"),
    ("jsonschema", "jsonschema", "jsonschema"),
    ("tqdm", "tqdm", "tqdm"),
    ("pytest", "pytest", "pytest"),
    ("black", "black", "black"),
    ("flake8", "flake8", "flake8"),
    ("mypy", "mypy", "mypy"),
    ("jupyter", "jupyter", "jupyter"),
    ("ipywidgets", "ipywidgets", "ipywidgets"),
]


def dependency_report(report=True):
    print("Testing imports...")
    rows = []
    
    for label, module_name, distribution_name in REQUIRED_IMPORTS:
        row = {
            "label": label,
            "module": module_name,
            "distribution": distribution_name,
            "installed": False,
            "imported": False,
            "version": "unknown",
            "error": "",
        }
        try:
            row["version"] = importlib.metadata.version(distribution_name)
            row["installed"] = True
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=DeprecationWarning)
                importlib.import_module(module_name)
            row["imported"] = True
            if report:
                print(f"  ✓ {label} {row['version']}")
        except (ImportError, importlib.metadata.PackageNotFoundError) as e:
            row["error"] = str(e)
            if report:
                print(f"  ✗ {label}: {e}")
        rows.append(row)
    
    return rows


def check_imports():
    return all(row["installed"] and row["imported"] for row in dependency_report())

def test_imports():
    rows = dependency_report()
    failed = [row for row in rows if not row["installed"] or not row["imported"]]
    if failed:
        details = "\n".join(
            f"- {row['label']} (module={row['module']}, dist={row['distribution']}): {row['error']}"
            for row in failed
        )
        pytest.fail(
            "dse_v2 dependency probe failed; install the declared environment with:\n"
            "  python3 -m pip install --user --break-system-packages -r dse_v2/requirements.txt\n"
            f"Missing or non-importable dependencies:\n{details}"
        )

def check_project_structure():
    print("\nTesting project structure...")
    project_root = Path(__file__).resolve().parents[1]
    
    required_dirs = [
        'architecture',
        'backends',
        'core',
        'core/workload',
        'interfaces',
        'reference_workloads',
        'design_space',
        'dse',
        'evidence',
        'mapping',
        'models',
        'promotion',
        'reporting',
        'scripts',
        'tests',
    ]
    
    all_exist = True
    for dir_name in required_dirs:
        dir_path = project_root / dir_name
        if dir_path.exists():
            print(f"  ✓ {dir_name}/")
        else:
            print(f"  ✗ {dir_name}/ (missing)")
            all_exist = False
    
    return all_exist

def test_project_structure():
    assert check_project_structure()

def check_fast_model():
    print("\nTesting fast performance model...")
    
    try:
        sys.path.append(str(Path.cwd()))
        from dse_v2.models.fast.performance_model import FastPerformanceModel
        
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
            'tile_problem_size': 1024,
            'tile_feature_size': 64,
            'tile_batch_size': 16,
            'intermediate_buffer_kb': 256,
        }
        
        workload = {'problem_size': 4096, 'feature_size': 256, 'batch_size': 16}
        
        result = model.evaluate_design_point(design_point, workload)
        
        print(f"  ✓ Model evaluation successful")
        print(f"    Time: {result['time_s']*1000:.2f} ms")
        print(f"    Energy: {result['energy_j']:.2f} J")
        print(f"    Feasible: {result['feasible']}")
        
        return True
    except Exception as e:
        print(f"  ✗ Model test failed: {e}")
        return False

def test_fast_model():
    assert check_fast_model()

def main():
    print("=" * 60)
    print("DSE v2 System Test")
    print("=" * 60)
    
    tests = [
        ("Imports", check_imports),
        ("Project Structure", check_project_structure),
        ("Fast Performance Model", check_fast_model),
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
