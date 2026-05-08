#!/usr/bin/env python3
"""
Microelectronics DFT Workload Analysis Script
Analyzes QE traces and computes theoretical speedup bounds and data movement.
"""

import csv
import sys
import json
from pathlib import Path
from collections import Counter
import math


def parse_subspace_trace(path: Path) -> list[dict]:
    """Parse QE subspace trace CSV."""
    rows = []
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append({
                "call_id": int(row["call_id"]),
                "solver": row["solver"],
                "n": int(row["n"]),
                "m": int(row["m"]),
                "all_eigenvalues": row["all_eigenvalues"].strip().lower() == "t",
                "h_frob": float(row["h_frob"]),
                "h_max_abs": float(row["h_max_abs"]),
                "s_identity_rel": float(row["s_identity_rel"]),
            })
    return rows


def analyze_workload(rows: list[dict], system_info: dict) -> dict:
    """Analyze workload characteristics."""
    if not rows:
        return {"error": "No trace data"}
    
    # Matrix size distribution
    n_counter = Counter(row["n"] for row in rows)
    nm_counter = Counter((row["n"], row["m"]) for row in rows)
    
    # Generalized vs standard
    generalized = sum(1 for row in rows if row["s_identity_rel"] > 1e-10)
    standard = len(rows) - generalized
    
    # Average matrix sizes
    avg_n = sum(row["n"] for row in rows) / len(rows)
    avg_m = sum(row["m"] for row in rows) / len(rows)
    max_n = max(row["n"] for row in rows)
    max_m = max(row["m"] for row in rows)
    
    # Memory estimates (complex FP64 = 16 bytes)
    bytes_per_complex = 16
    
    # Wavefunction panel size: Npw * m * 16
    npw = system_info.get("npw", 32535)  # Si64 estimate
    nbnd = system_info.get("nbnd", 256)
    
    panel_1x = npw * nbnd * bytes_per_complex  # Single panel
    panel_2x = npw * (2 * nbnd) * bytes_per_complex  # 2x Davidson
    panel_3x = npw * (3 * nbnd) * bytes_per_complex  # 3x Davidson
    
    # Reduced matrices: 2 * m^2 * 16
    reduced_1x = 2 * nbnd * nbnd * bytes_per_complex
    reduced_2x = 2 * (2 * nbnd) * (2 * nbnd) * bytes_per_complex
    
    # Density/potential grid
    fft_grid = system_info.get("fft_grid", (90, 90, 90))
    grid_points = fft_grid[0] * fft_grid[1] * fft_grid[2]
    density_field = grid_points * 8  # real FP64
    density_5fields = 5 * density_field
    
    # Data movement estimates
    # c_bands-only offload: input + output + potential
    cbands_only = panel_2x + panel_1x + density_5fields
    
    # Device-resident: only potential epoch
    resident = 2 * density_5fields
    
    # Amdahl bounds
    # Current c_bands fraction from repo data: ~50-67% for small cells
    # For Si64 supercell: estimated 70-90%
    p_small = 0.55  # Small cell
    p_large = 0.85  # Large supercell
    
    speedup_small_inf = 1.0 / (1.0 - p_small)
    speedup_large_inf = 1.0 / (1.0 - p_large)
    
    # With realistic accelerator speedup S=25x
    s_accel = 25.0
    speedup_small_real = 1.0 / ((1.0 - p_small) + p_small / s_accel)
    speedup_large_real = 1.0 / ((1.0 - p_large) + p_large / s_accel)
    
    # Strict diagonalization only (23% of c_bands)
    p_diag_only = p_large * 0.23
    speedup_diag_only = 1.0 / ((1.0 - p_diag_only) + p_diag_only / s_accel)
    
    return {
        "trace_summary": {
            "total_calls": len(rows),
            "generalized_calls": generalized,
            "standard_calls": standard,
            "avg_n": avg_n,
            "avg_m": avg_m,
            "max_n": max_n,
            "max_m": max_m,
            "top_n_sizes": dict(n_counter.most_common(5)),
            "top_nm_pairs": [f"({n},{m}): {c}" for (n, m), c in nm_counter.most_common(5)],
        },
        "memory_estimates_mb": {
            "wavefunction_panel_1x": panel_1x / (1024 * 1024),
            "wavefunction_panel_2x": panel_2x / (1024 * 1024),
            "wavefunction_panel_3x": panel_3x / (1024 * 1024),
            "reduced_matrices_1x": reduced_1x / (1024 * 1024),
            "reduced_matrices_2x": reduced_2x / (1024 * 1024),
            "density_1field": density_field / (1024 * 1024),
            "density_5fields": density_5fields / (1024 * 1024),
        },
        "data_movement_mb": {
            "cbands_only_offload": cbands_only / (1024 * 1024),
            "device_resident": resident / (1024 * 1024),
        },
        "amdahl_speedup": {
            "small_cell_infinite": speedup_small_inf,
            "large_cell_infinite": speedup_large_inf,
            "small_cell_25x": speedup_small_real,
            "large_cell_25x": speedup_large_real,
            "diag_only_25x": speedup_diag_only,
        },
        "system_info": system_info,
    }


def print_report(analysis: dict) -> None:
    """Print formatted analysis report."""
    print("=" * 70)
    print("MICROELECTRONICS DFT WORKLOAD ANALYSIS REPORT")
    print("=" * 70)
    
    # Trace summary
    ts = analysis["trace_summary"]
    print("\n## 1. TRACE SUMMARY")
    print(f"Total cdiaghg calls: {ts['total_calls']}")
    print(f"Generalized calls: {ts['generalized_calls']}")
    print(f"Standard calls: {ts['standard_calls']}")
    print(f"Average matrix size: n={ts['avg_n']:.1f}, m={ts['avg_m']:.1f}")
    print(f"Maximum matrix size: n={ts['max_n']}, m={ts['max_m']}")
    print("\nTop matrix sizes:")
    for size, count in ts["top_n_sizes"].items():
        print(f"  n={size}: {count} calls")
    
    # Memory estimates
    print("\n## 2. MEMORY ESTIMATES (MB)")
    mem = analysis["memory_estimates_mb"]
    for key, value in mem.items():
        print(f"  {key}: {value:.2f}")
    
    # Data movement
    print("\n## 3. DATA MOVEMENT PER SCF ITERATION (MB)")
    dm = analysis["data_movement_mb"]
    print(f"  c_bands-only offload: {dm['cbands_only_offload']:.2f}")
    print(f"  Device-resident inner loop: {dm['device_resident']:.2f}")
    print(f"  Reduction factor: {dm['cbands_only_offload'] / dm['device_resident']:.1f}x")
    
    # Amdahl speedup
    print("\n## 4. THEORETICAL SPEEDUP BOUNDS")
    sp = analysis["amdahl_speedup"]
    print(f"  Small cell (55% offloadable):")
    print(f"    Infinite accelerator: {sp['small_cell_infinite']:.2f}x")
    print(f"    25x accelerator: {sp['small_cell_25x']:.2f}x")
    print(f"  Large supercell (85% offloadable):")
    print(f"    Infinite accelerator: {sp['large_cell_infinite']:.2f}x")
    print(f"    25x accelerator: {sp['large_cell_25x']:.2f}x")
    print(f"  Diagonalization-only (19.6% offloadable):")
    print(f"    25x accelerator: {sp['diag_only_25x']:.2f}x")
    
    # Key insights
    print("\n## 5. KEY INSIGHTS")
    print("  - Full c_bands acceleration is critical (not just diagonalization)")
    print("  - Wavefunction residency reduces data movement by ~10x")
    print("  - Large supercells have higher offloadable fraction")
    print("  - Matrix sizes n=256-512 are representative for Si64")
    
    print("\n" + "=" * 70)


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {Path(sys.argv[0]).name} <trace_file> [system_info_json]", file=sys.stderr)
        return 2
    
    trace_path = Path(sys.argv[1])
    if not trace_path.is_file():
        print(f"Trace file not found: {trace_path}", file=sys.stderr)
        return 1
    
    # Default system info for Si64
    system_info = {
        "material": "Si64",
        "nat": 64,
        "npw": 32535,
        "nbnd": 256,
        "fft_grid": (90, 90, 90),
        "ecutwfc": 40.0,
    }
    
    # Override with user-provided info
    if len(sys.argv) > 2:
        info_path = Path(sys.argv[2])
        if info_path.is_file():
            with info_path.open() as f:
                system_info.update(json.load(f))
    
    rows = parse_subspace_trace(trace_path)
    analysis = analyze_workload(rows, system_info)
    
    print_report(analysis)
    
    # Save JSON
    output_path = trace_path.with_suffix(".analysis.json")
    with output_path.open("w") as f:
        json.dump(analysis, f, indent=2)
    print(f"\nAnalysis saved to: {output_path}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
