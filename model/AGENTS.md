# AGENTS Guide - Model Directory

## Purpose

This directory contains the core computational models for the DFT acceleration system:

- **ozaki_subspace_model/**: Standalone behavioral evaluators for Ozaki-II GEMM, CRT arithmetic, and generalized Hermitian eigensolver validation
- **qe_band_solver_model/**: SystemC timed-functional model of the QE-connected band-solver subsystem with 4-Cluster pipeline architecture

Both models serve as algorithmic validation platforms and system-level performance estimation tools before RTL implementation.

## Directory Structure

```
model/
├── ozaki_subspace_model/     # Standalone C++ evaluators (Makefile-based)
│   ├── include/              # Shared headers for evaluators
│   ├── src/                  # C++ source files
│   ├── bin/                  # Build outputs
│   └── docs/                 # Validation reports
├── qe_band_solver_model/     # SystemC model (CMake-based)
│   ├── include/              # SystemC module headers
│   ├── src/                  # SystemC implementation
│   ├── build/                # CMake build directory
│   └── docs/                 # Model validation notes
└── README.md                 # Model index
```

## Build System Overview

- **ozaki_subspace_model**: Uses standalone `Makefile`, builds 4 independent executables
- **qe_band_solver_model**: Uses `CMake`, builds single SystemC executable with modular architecture

## Quick Start

### Build Ozaki Evaluators
```bash
make -C model/ozaki_subspace_model
```

### Build QE Band Solver Model
```bash
cd model/qe_band_solver_model
mkdir -p build && cd build
cmake ..
make -j4
```

### Run Examples
```bash
# Ozaki-II GEMM validation
./model/ozaki_subspace_model/bin/complex_ozaki_eval

# Generalized eigensolver validation
./model/ozaki_subspace_model/bin/generalized_subspace_eval

# SystemC band-solver simulation
./model/qe_band_solver_model/build/qe_band_solver_sim
```

## Model Relationships

```
QE Real Workload (soft/qe-7.5/)
    ↓ (trace extraction)
docs/benchmarks/ (Python analysis)
    ↓ (parameter extraction)
ozaki_subspace_model/ (algorithm validation)
    ↓ (algorithm freeze)
qe_band_solver_model/ (system simulation)
    ↓ (performance estimation)
DSE Framework (docs/benchmarks/run_systemc_architecture_family_dse_sweep.py)
```

## Key Validation Artifacts

- **Ozaki-II GEMM**: Validates complex FP64 GEMM using Ozaki-II + CRT + Karatsuba 3M
- **Generalized Eigensolver**: Validates LAPACK-based generalized Hermitian solver against QE dumps
- **Iterative Subspace**: Validates iterative refinement for reduced-space problems
- **SystemC Model**: Validates Host-FPGA-Chip transaction semantics and timing estimates

## Testing Philosophy

- **Ozaki models**: Numerical correctness against reference BLAS/LAPACK
- **QE band solver model**: Transaction semantics and cycle-count estimation
- **No unit test framework**: Each executable is a self-contained validation testbench

## Documentation

- See subdirectory AGENTS.md files for detailed build/run/test instructions
- See `docs/overview/project_development_timeline.md` for system context
- See `docs/architecture/system_design_master_spec_v0.md` for system contracts

## Common Workflows

### Algorithm Validation
1. Extract QE trace data from `soft/qe-7.5/`
2. Run appropriate ozaki_subspace_model evaluator
3. Verify numerical accuracy against reference implementation

### System Performance Estimation
1. Configure architecture parameters in qe_band_solver_model
2. Run SystemC simulation with QE-derived workload parameters
3. Extract cycle counts and resource utilization
4. Feed results to DSE framework for architecture exploration

### DSE Integration
1. Both models provide performance data to DSE sweep scripts
2. DSE framework in `docs/benchmarks/` orchestrates parameter exploration
3. Results inform architecture decisions and paper claims

## Critical Rules

- Do not modify QE installation at `/Users/xixilys/project/qe-7.5`
- Use workspace copy at `soft/qe-7.5/` for instrumentation
- Preserve numerical contracts when modifying evaluators
- Update corresponding docs/ when changing model behavior
- Run validation after any algorithm changes

## Next Steps

- For Ozaki model details: see `model/ozaki_subspace_model/AGENTS.md`
- For SystemC model details: see `model/qe_band_solver_model/AGENTS.md`
- For system-level context: see root `AGENTS.md`
