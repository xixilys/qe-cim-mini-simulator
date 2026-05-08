# AGENTS Guide - dse_v2

## Purpose

Next-generation Design Space Exploration framework using Bayesian Optimization. Explores Host+FPGA two-tier architecture without Chip-level constraints.

**Goals:**
- Simplified architecture (Host+FPGA only)
- Extended workload coverage
- Modern BO-based search (replaces rule-based DSE)
- Open design space beyond 4-cluster pipeline

## Directory Structure

```
dse_v2/
├── workloads/          # Workload traces and definitions
├── design_space/       # Parameter space and constraints
├── models/             # Performance models (fast/mid/high fidelity)
├── optimization/       # BO, evolutionary, hybrid algorithms
├── results/            # Pareto frontiers and reports
├── scripts/            # Setup, workload, DSE, analysis
├── docs/               # Design docs and tutorials
└── tests/              # Unit and integration tests
```

## Key Entry Points

```bash
# Analyze existing workloads
python3 scripts/workload/analyze_existing_workloads.py

# Define design space
python3 scripts/setup/define_design_space.py

# Run Bayesian Optimization
python3 scripts/dse/run_bayesian_dse.py --workload si8_pbe_uspp --iterations 50
```

## Dependencies

- Python 3.9+
- PyTorch 2.0+
- BoTorch 0.9+
- Ax Platform 0.3+

See `requirements.txt`

## Integration Points

- **With docs/benchmarks/**: Consumes QE traces and workload definitions
- **With model/**: May invoke performance models for evaluation
- **With soft/qe-7.5/**: Uses instrumented QE for trace extraction

## Status

Experimental / next-generation. Does not replace mainline DSE in `docs/benchmarks/`.

## Next Steps

- For mainline DSE: see `docs/benchmarks/AGENTS.md`
- For workload data: see `docs/overview/qe_subspace_sampling.md`
- For system model: see `model/qe_band_solver_model/AGENTS.md`
