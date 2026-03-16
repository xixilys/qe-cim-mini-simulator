# AGENTS Guide

## Purpose

- This repository is a prototype for accelerating Quantum ESPRESSO style subspace diagonalization and dense kernels with a CIM-oriented backend.
- The main implementation lives in `model/` and the main design context lives in `docs/`.
- Treat the codebase as research software: preserve reproducibility, numerical intent, and paper-facing assumptions.

## Repository Layout

- `model/`: SystemC-based simulator, behavioral testbenches, and validation executables.
- `model/include/`: project headers shared by SystemC modules and evaluators.
- `model/src/`: C++ sources for the simulator and standalone evaluators.
- `model/bin/`: build outputs created by `make`.
- `model/docs/`: validation notes and architecture documents for the simulator.
- `docs/`: project-level design notes, benchmark workflows, QE sampling notes, and handoff context.
- `docs/benchmarks/`: Python scripts for trace summarization and CPU/PySCF baselines.
- `soft/qe-7.5/`: workspace copy of QE used for trace instrumentation and local experiments.

## Critical Workspace Rules

- Do not modify `/Users/xixilys/project/qe-7.5`.
- If QE changes are needed, only touch the workspace copy at `soft/qe-7.5/`.
- Expect a dirty working tree; do not revert unrelated user changes.
- Large trace CSVs and dump directories are part of the workflow; avoid rewriting them unless the task explicitly requires it.

## Existing Agent / Editor Rules

- No `.cursorrules` file was found.
- No `.cursor/rules/` directory was found.
- No `.github/copilot-instructions.md` file was found.
- The main repo-specific agent guidance currently comes from `docs/agent_handoff_20260312.md`; follow it when choosing priorities.

## Build Prerequisites

- macOS toolchain is assumed.
- SystemC headers and libraries must be available at the paths referenced by `model/Makefile`.
- The current `Makefile` uses `g++`, `-std=c++17`, `-O3`, `-Wall`, `/opt/homebrew/include`, `/opt/homebrew/lib`, `-lsystemc`, and `-framework Accelerate` for the generalized eigensolver executable.

## Primary Build Commands

- Build everything:
  - `make -C model`
- Build the complex Ozaki evaluator only:
  - `make -C model bin/complex_ozaki_eval`
- Build the generalized subspace evaluator only:
  - `make -C model bin/generalized_subspace_eval`
- Build the iterative subspace evaluator only:
  - `make -C model bin/iterative_subspace_eval`
- Build the iterative tile GEMM evaluator only:
  - `make -C model bin/iterative_tile_gemm_eval`
- Clean build artifacts:
  - `make -C model clean`

## Run Commands

- Run the complex Ozaki evaluator:
  - `./model/bin/complex_ozaki_eval`
- Run the generalized subspace evaluator:
  - `./model/bin/generalized_subspace_eval`
- Run the iterative subspace evaluator:
  - `./model/bin/iterative_subspace_eval`
- Run the iterative tile GEMM evaluator:
  - `./model/bin/iterative_tile_gemm_eval`

## Single-Test Guidance

- This repository does not use a unit-test framework such as `pytest`, `ctest`, or GoogleTest.
- A "single test" usually means building and running one standalone evaluator executable.
- Use one of these focused commands:
  - `make -C model bin/complex_ozaki_eval && ./model/bin/complex_ozaki_eval`
  - `make -C model bin/generalized_subspace_eval && ./model/bin/generalized_subspace_eval`
  - `make -C model bin/iterative_subspace_eval && ./model/bin/iterative_subspace_eval`
  - `make -C model bin/iterative_tile_gemm_eval && ./model/bin/iterative_tile_gemm_eval`
- For faster iteration, rebuild only the executable affected by the file you changed instead of running `make` for the whole directory.

## Parameterized Test Runs

- `complex_ozaki_eval` supports environment overrides such as:
  - `OZAKI_EXP_SPAN=64 OZAKI_TRIALS=4 ./model/bin/complex_ozaki_eval`
- `generalized_subspace_eval` supports environment overrides such as:
  - `GEN_SUBSPACE_DIRS=/abs/path/dir1,/abs/path/dir2 ./model/bin/generalized_subspace_eval`
  - `GEN_SUBSPACE_MAX_CASES=8 ./model/bin/generalized_subspace_eval`
- `iterative_subspace_eval` supports environment overrides such as:
  - `ITER_USE_QE_CASE=0 ITER_STEPS=4 ./model/bin/iterative_subspace_eval`
- `iterative_tile_gemm_eval` supports environment overrides such as:
  - `ITER_USE_QE_CASE=0 ITER_N=32 ITER_M=16 ./model/bin/iterative_tile_gemm_eval`
- When reporting results, include the executable name, environment variables, and dataset or dump directory used.

## Benchmark / Analysis Commands

- Summarize a QE trace CSV:
  - `python3 docs/benchmarks/summarize_qe_subspace_trace.py /abs/path/qe_subspace_trace.csv`
- Rebuild the traced QE workspace copy when needed:
  - `cmake --build /Volumes/remote/phd/year_2/project/dft加速/soft/qe-7.5/build_subspace_trace --target qe_pw_exe -j4`
- Additional benchmark helpers exist in:
  - `docs/benchmarks/run_cpu_baseline.py`
  - `docs/benchmarks/run_pyscf_ops_baseline.py`

## Lint / Formatting Status

- No dedicated lint target was found.
- No formatter configuration (`.clang-format`, `pyproject.toml`, `ruff.toml`, etc.) was found in the inspected files.
- Do not introduce a new formatter or linter configuration unless the task explicitly asks for it.
- Match the style already present in each edited file.

## C++ Style Guidelines

- Use C++17-compatible code.
- Favor standard library facilities over custom helpers when the existing code already uses them.
- Keep helper functions `static` at file scope when they are local to one translation unit.
- Prefer simple structs for plain data containers used by testbenches and evaluators.
- Keep matrix and numerical helpers near the top of the file before `sc_main`.
- Preserve the current research-prototype style: direct, explicit loops are preferred over clever abstractions.

## Include / Import Conventions

- Put `#include <systemc.h>` first in SystemC translation units, matching the current sources.
- Keep platform-specific or framework-specific includes near the top, e.g. `#include <Accelerate/Accelerate.h>`.
- Group standard library includes together after framework headers.
- Include local project headers after system and standard headers.
- Python imports follow the usual grouping: stdlib first; there is no evidence of third-party imports in the inspected scripts.

## Formatting Conventions

- Use 4 spaces for indentation in C++ and Python.
- Keep braces on the same line for functions, loops, and conditionals.
- Use a space before `{` and around binary operators.
- Favor short, readable single-line conditionals only when they remain clear.
- Keep lines reasonably compact, but there is no enforced hard wrap.
- Maintain existing blank-line spacing between logical helper blocks.

## Types and Numeric Code

- Use `int` for small matrix dimensions and loop indices when consistent with the surrounding code.
- Use `size_t` when iterating over container sizes that already expose `size()`.
- Use explicit aliases when binding external numeric APIs, e.g. `using LapackInt = __CLPK_integer`.
- Use `std::vector<T>` for owned buffers.
- Use `std::complex<double>` or split real/imag arrays depending on the local file's established representation.
- When precision matters, keep computations in `double` or `long double` as the existing implementation does.
- Preserve row-major vs column-major assumptions explicitly; document conversions in code structure, not with redundant comments.

## Naming Conventions

- Types use `UpperCamelCase`, e.g. `ComplexMatrix`, `CaseMetrics`, `FPGA_Controller`.
- Functions use `snake_case`, e.g. `hermitianize`, `compare_complex`, `compute_energy_terms`.
- Environment variable helpers use `env_*` names.
- Local variables are short and math-oriented when appropriate: `n`, `m`, `k`, `acc`, `evals`, `eigvecs`.
- Constants are often `static` functions rather than global `constexpr` values; follow the surrounding file.
- Preserve domain terminology from QE, BLAS, and eigensolver math instead of renaming to generic terms.

## Error Handling and Validation

- Prefer explicit success checks on LAPACK and file operations.
- Return `bool` from helper routines that can fail numerically or via backend calls.
- Clamp denominators with guards such as `std::max(1e-30, value)` when computing relative errors or norms.
- Keep failure handling lightweight and local; this codebase does not use exceptions as a primary control-flow mechanism.
- For CLI-style scripts, return nonzero exit codes on invalid arguments or missing files.
- When adding new validation paths, report both absolute and relative error metrics when possible.

## Testing Expectations For Changes

- If you edit `model/src/tb_complex_ozaki.cpp`, rebuild and run `bin/complex_ozaki_eval`.
- If you edit `model/src/tb_generalized_subspace.cpp`, rebuild and run `bin/generalized_subspace_eval`.
- If you edit `model/src/tb_iterative_subspace.cpp` or `model/src/iterative_subspace_engine.cpp`, rebuild and run `bin/iterative_subspace_eval`.
- If you edit `model/src/tb_iterative_tile_gemm.cpp` or `model/src/iterative_subspace_engine.cpp`, rebuild and run `bin/iterative_tile_gemm_eval`.
- If you edit Python benchmark scripts, run the specific script with a known input file rather than adding unrelated tooling.

## Documentation Expectations

- Keep design-facing rationale in `docs/` or `model/docs/`, not buried in source comments.
- When behavior changes, update the corresponding validation note if the command, metric, or conclusion changes.
- Prefer documenting reproducible commands with absolute or workspace-relative paths.

## Current Project Priorities

- The handoff document indicates the most important open work is algorithm freezing, not rebuilding the QE dataset from scratch.
- Generalized Hermitian eigensolver work and Ozaki/CRT design decisions are the current mainline topics.
- Avoid spending time on unrelated refactors unless they unblock the requested task.

## Good Agent Behavior In This Repo

- Read `docs/agent_handoff_20260312.md` before making large design or documentation changes.
- Preserve existing numerical contracts and reported metrics.
- Make focused edits, then run the smallest relevant build or evaluator.
- In final reports, mention exactly which executable or script you ran and which file paths you changed.
