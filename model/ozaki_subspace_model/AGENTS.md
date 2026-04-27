# AGENTS Guide - Ozaki Subspace Model

## Purpose

Standalone C++ evaluators for validating algorithmic components before SystemC integration:

- **Ozaki-II GEMM**: Complex FP64 matrix multiplication using Ozaki-II + CRT + Karatsuba 3M
- **Generalized Eigensolver**: LAPACK-based generalized Hermitian eigensolver validation
- **Iterative Subspace**: Iterative refinement engine for reduced-space problems
- **Iterative Tile GEMM**: Tiled GEMM validation for blocked algorithms

All evaluators are self-contained testbenches with numerical validation against reference implementations.

## Build System

Uses standalone `Makefile` with the following configuration:

- **Compiler**: `g++` with `-std=c++17 -O3`
- **Dependencies**: SystemC (libsystemc), Accelerate framework (macOS)
- **Include paths**: `include/`, `/opt/homebrew/include`
- **Library paths**: `/opt/homebrew/lib`

## Executables

| Executable | Source Files | Purpose | Dependencies |
|------------|--------------|---------|--------------|
| `bin/complex_ozaki_eval` | `tb_complex_ozaki.cpp` | Ozaki-II GEMM validation | SystemC |
| `bin/generalized_subspace_eval` | `tb_generalized_subspace.cpp` | Generalized eigensolver validation | SystemC, Accelerate |
| `bin/iterative_subspace_eval` | `tb_iterative_subspace.cpp`, `iterative_subspace_engine.cpp` | Iterative subspace refinement | SystemC |
| `bin/iterative_tile_gemm_eval` | `tb_iterative_tile_gemm.cpp`, `iterative_subspace_engine.cpp` | Tiled GEMM validation | SystemC |
| `bin/iterative_micro_compare_eval` | `tb_iterative_micro_compare.cpp`, `iterative_subspace_engine.cpp` | Micro-benchmark comparison | SystemC, Accelerate |
| `bin/iterative_qe_regression_eval` | `tb_iterative_qe_regression.cpp`, `iterative_subspace_engine.cpp` | QE regression testing | SystemC, Accelerate |

## Build Commands

### Build All Executables
```bash
make -C model/ozaki_subspace_model
```

### Build Individual Executables
```bash
make -C model/ozaki_subspace_model bin/complex_ozaki_eval
make -C model/ozaki_subspace_model bin/generalized_subspace_eval
make -C model/ozaki_subspace_model bin/iterative_subspace_eval
make -C model/ozaki_subspace_model bin/iterative_tile_gemm_eval
```

### Clean Build Artifacts
```bash
make -C model/ozaki_subspace_model clean
```

## Run Commands

### Complex Ozaki Evaluator
```bash
./model/ozaki_subspace_model/bin/complex_ozaki_eval
```

**Environment Variables:**
- `OZAKI_EXP_SPAN`: Exponent span for Ozaki-II (default: varies by testbench)
- `OZAKI_TRIALS`: Number of random trials (default: varies by testbench)

**Example:**
```bash
OZAKI_EXP_SPAN=64 OZAKI_TRIALS=4 ./model/ozaki_subspace_model/bin/complex_ozaki_eval
```

### Generalized Subspace Evaluator
```bash
./model/ozaki_subspace_model/bin/generalized_subspace_eval
```

**Environment Variables:**
- `GEN_SUBSPACE_DIRS`: Comma-separated list of QE dump directories
- `GEN_SUBSPACE_MAX_CASES`: Maximum number of cases to process

**Example:**
```bash
GEN_SUBSPACE_DIRS=/path/to/dump1,/path/to/dump2 ./model/ozaki_subspace_model/bin/generalized_subspace_eval
```

### Iterative Subspace Evaluator
```bash
./model/ozaki_subspace_model/bin/iterative_subspace_eval
```

**Environment Variables:**
- `ITER_USE_QE_CASE`: Use QE case (1) or synthetic (0)
- `ITER_STEPS`: Number of iterative refinement steps

**Example:**
```bash
ITER_USE_QE_CASE=0 ITER_STEPS=4 ./model/ozaki_subspace_model/bin/iterative_subspace_eval
```

### Iterative Tile GEMM Evaluator
```bash
./model/ozaki_subspace_model/bin/iterative_tile_gemm_eval
```

**Environment Variables:**
- `ITER_USE_QE_CASE`: Use QE case (1) or synthetic (0)
- `ITER_N`: Matrix dimension N
- `ITER_M`: Matrix dimension M

**Example:**
```bash
ITER_USE_QE_CASE=0 ITER_N=32 ITER_M=16 ./model/ozaki_subspace_model/bin/iterative_tile_gemm_eval
```

## Key Source Files

### Testbenches (src/)
- `tb_complex_ozaki.cpp`: Ozaki-II GEMM testbench with random matrix generation
- `tb_generalized_subspace.cpp`: Generalized eigensolver testbench with QE dump loading
- `tb_iterative_subspace.cpp`: Iterative subspace refinement testbench
- `tb_iterative_tile_gemm.cpp`: Tiled GEMM testbench
- `tb_iterative_micro_compare.cpp`: Micro-benchmark comparison testbench
- `tb_iterative_qe_regression.cpp`: QE regression testing testbench

### Shared Engine (src/ + include/)
- `iterative_subspace_engine.cpp`: Core iterative refinement engine implementation
- `iterative_subspace_engine.h`: Engine interface and data structures

## Validation Methodology

### Ozaki-II GEMM
- Generates random complex FP64 matrices
- Computes C = A * B using Ozaki-II + CRT + Karatsuba 3M
- Validates against reference BLAS implementation
- Reports absolute and relative errors

### Generalized Eigensolver
- Loads H_sub and S_sub from QE dump directories
- Solves generalized Hermitian eigenproblem using LAPACK
- Validates eigenvalues and eigenvectors
- Reports residual norms and orthogonality errors

### Iterative Subspace
- Tests iterative refinement for reduced-space problems
- Validates convergence behavior
- Reports iteration counts and residual reduction

### Iterative Tile GEMM
- Tests tiled GEMM implementation
- Validates against reference BLAS
- Reports performance and accuracy metrics

## Numerical Contracts

- **Precision**: FP64 throughout (no mixed precision in evaluators)
- **Complex arithmetic**: `std::complex<double>` or split real/imag arrays
- **Matrix layout**: Column-major (LAPACK/BLAS convention)
- **Error tolerance**: Typically 1e-10 to 1e-12 for relative errors
- **Hermitian property**: Explicitly enforced via `hermitianize()` helpers

## Common Workflows

### Validate Ozaki-II Algorithm
1. Build `bin/complex_ozaki_eval`
2. Run with various `OZAKI_EXP_SPAN` values
3. Verify errors are within tolerance
4. Document results in `docs/`

### Validate Against QE Dumps
1. Extract QE dumps using `docs/overview/qe_subspace_sampling.md`
2. Build `bin/generalized_subspace_eval`
3. Run with `GEN_SUBSPACE_DIRS` pointing to dump directories
4. Verify eigenvalues match QE output
5. Document validation in `docs/`

### Test Iterative Refinement
1. Build `bin/iterative_subspace_eval`
2. Run with synthetic or QE cases
3. Verify convergence behavior
4. Document iteration counts and residuals

### Regression Testing
1. Build `bin/iterative_qe_regression_eval`
2. Run against known QE cases
3. Verify no regressions in accuracy or convergence
4. Update regression baseline if needed

## Testing Expectations

- **After editing `tb_complex_ozaki.cpp`**: Rebuild and run `bin/complex_ozaki_eval`
- **After editing `tb_generalized_subspace.cpp`**: Rebuild and run `bin/generalized_subspace_eval`
- **After editing `tb_iterative_subspace.cpp` or `iterative_subspace_engine.cpp`**: Rebuild and run `bin/iterative_subspace_eval`
- **After editing `tb_iterative_tile_gemm.cpp`**: Rebuild and run `bin/iterative_tile_gemm_eval`

## Code Style

- **C++17** standard
- **4-space indentation**
- **snake_case** for functions
- **UpperCamelCase** for types
- **Static helpers** at file scope for testbench-local utilities
- **Explicit loops** preferred over abstractions (research prototype style)
- **Numerical helpers** near top of file before `sc_main`

## Error Handling

- Explicit success checks on LAPACK calls
- Return `bool` from helpers that can fail
- Clamp denominators with `std::max(1e-30, value)` for relative errors
- Report both absolute and relative errors
- Exit with nonzero code on validation failure

## Documentation

- Validation results go in `docs/` subdirectory
- Include executable name, environment variables, and dataset paths
- Document numerical accuracy, convergence behavior, and performance
- Update validation notes when algorithm changes

## Integration with SystemC Model

These evaluators validate algorithms before integration into `qe_band_solver_model`:

1. Algorithm validated here → frozen
2. Frozen algorithm → integrated into SystemC modules
3. SystemC model → used for system-level performance estimation

## Critical Rules

- Preserve numerical contracts when modifying algorithms
- Run validation after any algorithm changes
- Document validation results in `docs/`
- Do not modify QE dumps or trace data
- Match existing code style in each file

## Next Steps

- For SystemC integration: see `model/qe_band_solver_model/AGENTS.md`
- For QE dump extraction: see `docs/overview/qe_subspace_sampling.md`
- For system context: see `docs/overview/project_development_timeline.md`
