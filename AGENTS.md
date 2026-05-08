# AGENTS Guide

## Purpose

DFT acceleration system prototype for Quantum ESPRESSO subspace diagonalization with CIM-oriented backend.

**System Architecture:**
- **Host + FPGA + Chip**: Complete hybrid acceleration system
- **4-Cluster Pipeline**: Operator sweep (68%), reduced build (4%), hardware diag (23%), refresh/residual (5%)
- **Dual Model Stack**: Algorithm validation (Ozaki) + System simulation (SystemC)

**Project Status:** ~90% complete infrastructure, algorithm validation in progress

## Quick Navigation

### For Implementation Work
- **Algorithm validation**: See `model/ozaki_subspace_model/AGENTS.md`
- **SystemC model**: See `model/qe_band_solver_model/AGENTS.md`
- **Architecture specs**: See `docs/architecture/AGENTS.md`
- **DSE framework**: See `docs/benchmarks/AGENTS.md`

### For Design Review
1. `docs/architecture/system_design_master_spec_v0.md` - Master system specification
2. `docs/overview/project_development_timeline.md` - Development timeline
3. `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md` - Fairness contract
4. `docs/overview/agent_handoff_20260312.md` - Repository handoff notes

### For Quick Start
```bash
# Build and run algorithm validation
make -C model/ozaki_subspace_model
./model/ozaki_subspace_model/bin/complex_ozaki_eval

# Build and run SystemC model
cd model/qe_band_solver_model/build
cmake .. && make -j4
./qe_band_solver_model

# Run DSE sweep
python3 docs/benchmarks/run_systemc_architecture_family_dse_sweep.py
```

## Repository Layout

```
.
├── AGENTS.md                       # Root guide (this file)
├── model/                          # Implementation models
│   ├── AGENTS.md                   # Model directory guide
│   ├── ozaki_subspace_model/       # Algorithm validation (Ozaki-II, eigensolver)
│   │   ├── AGENTS.md               # Detailed guide for algorithm validation
│   │   ├── src/                    # C++ testbenches and engines
│   │   ├── include/                # Headers
│   │   ├── bin/                    # Built executables
│   │   └── Makefile                # Standalone build system
│   └── qe_band_solver_model/       # SystemC system simulation
│       ├── AGENTS.md               # Detailed guide for SystemC model
│       ├── src/                    # SystemC modules
│       ├── include/                # Module headers
│       └── CMakeLists.txt          # CMake build system
├── docs/                           # Design documentation
│   ├── AGENTS.md                   # Documentation directory guide
│   ├── architecture/               # System architecture specs
│   │   ├── AGENTS.md               # Architecture guide
│   │   ├── system_design_master_spec_v0.md
│   │   ├── qe_ic_component_catalog_system_level_v1.json
│   │   └── qe_ic_graph_seed_system_level_v1.json
│   ├── benchmarks/                 # DSE framework and validation
│   │   ├── AGENTS.md               # Benchmarks guide
│   │   ├── run_systemc_architecture_family_dse_sweep.py
│   │   └── 50+ analysis/validation scripts
│   ├── overview/                   # Project timeline and handoff
│   ├── cim/                        # CIM design specifications
│   ├── control/                    # Control ISA specifications
│   └── survey/                     # Industry surveys
├── gem5_integration/               # gem5+SystemC co-simulation
│   ├── AGENTS.md                   # Co-simulation guide
│   ├── src/dev/fpga/               # gem5 FPGA device model
│   ├── systemc_model/              # SystemC TLM model
│   ├── qe_integration/             # QE offload hooks
│   └── configs/fpga/               # gem5 system configs
├── dse_v2/                         # Next-gen Bayesian DSE framework
│   ├── AGENTS.md                   # DSE v2 guide
│   ├── workloads/                  # Workload definitions
│   ├── design_space/               # Parameter space
│   ├── models/                     # Performance models
│   └── optimization/               # BO algorithms
├── runtime_api/                    # Domain-neutral C ABI
│   ├── AGENTS.md                   # Runtime API guide
│   ├── command_descriptor.h        # Offload command descriptor
│   └── offload_runtime.h/.c        # Runtime implementation
├── Survey/                         # Research pipeline: survey stage
│   ├── AGENTS.md                   # Survey stage guide
│   ├── references/                 # Literature references
│   └── reports/                    # Survey reports
├── soft/qe-7.5/                    # QE workspace copy (instrumented)
└── tmp*/                           # Generated outputs and scratch
```

## ⚠️ CRITICAL: Background Task Protocol

**NEVER call `background_output()` before receiving `<system-reminder>` notification.**

This is a strict system-level protocol. Violating it causes "无法调用background task" errors and **permanent loss of all background work**.

### Correct Flow

```typescript
// Step 1: Launch parallel background tasks
task(subagent_type="explore", run_in_background=true, load_skills=[], 
     description="Find auth patterns", prompt="...")  
// → Returns task_id: bg_abc123

task(subagent_type="librarian", run_in_background=true, load_skills=[], 
     description="Find library docs", prompt="...")
// → Returns task_id: bg_def456

// Step 2: Do ONLY non-overlapping work (work that doesn't depend on these results)
// If no independent work exists: **END YOUR RESPONSE HERE**

// Step 3: **WAIT** for system notification
// The system will send: <system-reminder> [ALL BACKGROUND TASKS COMPLETE]

// Step 4: NOW collect results (only after notification)
background_output(task_id="bg_abc123")  // ✅ Safe
background_output(task_id="bg_def456")  // ✅ Safe

// Step 5: Use results, then cleanup
background_cancel(taskId="bg_abc123")
background_cancel(taskId="bg_def456")
```

### Common Mistakes That Cause Errors

- ❌ **Calling `background_output()` immediately after spawning** → Error: task still running
- ❌ **Continuing with dependent work before results arrive** → Incomplete/wrong results
- ❌ **Trying to "check" or poll task status** → System rejects premature access
- ❌ **Calling across sessions** → Task IDs expire when session ends

### Why This Protocol Exists

The system uses a state machine (`pending → running → completed`). Calling `background_output()` on a non-completed task triggers a state check failure. The `<system-reminder>` notification is the **only** reliable signal that results are ready.

### If You Violate This

1. You get error: "无法调用background task"
2. All background work is **permanently lost** (cannot be recovered)
3. You must re-spawn all tasks from scratch
4. Results are never collected from the failed attempt

### Recovery

If you encounter this error:
1. Background tasks from the failed attempt are gone
2. Re-spawn the tasks following the correct protocol
3. This time: **wait for `<system-reminder>` before collecting**

---

## Critical Workspace Rules

- Do not modify `/Users/xixilys/project/qe-7.5`.
- If QE changes are needed, only touch the workspace copy at `soft/qe-7.5/`.
- Expect a dirty working tree; do not revert unrelated user changes.
- Large trace CSVs and dump directories are part of the workflow; avoid rewriting them unless the task explicitly requires it.

## Existing Agent / Editor Rules

- No `.cursorrules` file was found.
- No `.cursor/rules/` directory was found.
- No `.github/copilot-instructions.md` file was found.
- The main repo-specific agent guidance currently comes from `docs/overview/agent_handoff_20260312.md`; follow it when choosing priorities.

## Build Prerequisites

- macOS toolchain is assumed.
- SystemC headers and libraries must be available at the paths referenced by `model/ozaki_subspace_model/Makefile`.
- The standalone evaluator `Makefile` uses `g++`, `-std=c++17`, `-O3`, `-Wall`, `/opt/homebrew/include`, `/opt/homebrew/lib`, `-lsystemc`, and `-framework Accelerate` for the generalized eigensolver executable.

## Primary Build Commands

- Build everything:
  - `make -C model/ozaki_subspace_model`
- Build the complex Ozaki evaluator only:
  - `make -C model/ozaki_subspace_model bin/complex_ozaki_eval`
- Build the generalized subspace evaluator only:
  - `make -C model/ozaki_subspace_model bin/generalized_subspace_eval`
- Build the iterative subspace evaluator only:
  - `make -C model/ozaki_subspace_model bin/iterative_subspace_eval`
- Build the iterative tile GEMM evaluator only:
  - `make -C model/ozaki_subspace_model bin/iterative_tile_gemm_eval`
- Clean build artifacts:
  - `make -C model/ozaki_subspace_model clean`

## Run Commands

- Run the complex Ozaki evaluator:
  - `./model/ozaki_subspace_model/bin/complex_ozaki_eval`
- Run the generalized subspace evaluator:
  - `./model/ozaki_subspace_model/bin/generalized_subspace_eval`
- Run the iterative subspace evaluator:
  - `./model/ozaki_subspace_model/bin/iterative_subspace_eval`
- Run the iterative tile GEMM evaluator:
  - `./model/ozaki_subspace_model/bin/iterative_tile_gemm_eval`

## Single-Test Guidance

- This repository does not use a unit-test framework such as `pytest`, `ctest`, or GoogleTest.
- A "single test" usually means building and running one standalone evaluator executable.
- Use one of these focused commands:
  - `make -C model/ozaki_subspace_model bin/complex_ozaki_eval && ./model/ozaki_subspace_model/bin/complex_ozaki_eval`
  - `make -C model/ozaki_subspace_model bin/generalized_subspace_eval && ./model/ozaki_subspace_model/bin/generalized_subspace_eval`
  - `make -C model/ozaki_subspace_model bin/iterative_subspace_eval && ./model/ozaki_subspace_model/bin/iterative_subspace_eval`
  - `make -C model/ozaki_subspace_model bin/iterative_tile_gemm_eval && ./model/ozaki_subspace_model/bin/iterative_tile_gemm_eval`
- For faster iteration, rebuild only the executable affected by the file you changed instead of running `make` for the whole directory.

## Parameterized Test Runs

- `complex_ozaki_eval` supports environment overrides such as:
  - `OZAKI_EXP_SPAN=64 OZAKI_TRIALS=4 ./model/ozaki_subspace_model/bin/complex_ozaki_eval`
- `generalized_subspace_eval` supports environment overrides such as:
  - `GEN_SUBSPACE_DIRS=/abs/path/dir1,/abs/path/dir2 ./model/ozaki_subspace_model/bin/generalized_subspace_eval`
  - `GEN_SUBSPACE_MAX_CASES=8 ./model/ozaki_subspace_model/bin/generalized_subspace_eval`
- `iterative_subspace_eval` supports environment overrides such as:
  - `ITER_USE_QE_CASE=0 ITER_STEPS=4 ./model/ozaki_subspace_model/bin/iterative_subspace_eval`
- `iterative_tile_gemm_eval` supports environment overrides such as:
  - `ITER_USE_QE_CASE=0 ITER_N=32 ITER_M=16 ./model/ozaki_subspace_model/bin/iterative_tile_gemm_eval`
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

- If you edit `model/ozaki_subspace_model/src/tb_complex_ozaki.cpp`, rebuild and run `bin/complex_ozaki_eval`.
- If you edit `model/ozaki_subspace_model/src/tb_generalized_subspace.cpp`, rebuild and run `bin/generalized_subspace_eval`.
- If you edit `model/ozaki_subspace_model/src/tb_iterative_subspace.cpp` or `model/ozaki_subspace_model/src/iterative_subspace_engine.cpp`, rebuild and run `bin/iterative_subspace_eval`.
- If you edit `model/ozaki_subspace_model/src/tb_iterative_tile_gemm.cpp` or `model/ozaki_subspace_model/src/iterative_subspace_engine.cpp`, rebuild and run `bin/iterative_tile_gemm_eval`.
- If you edit Python benchmark scripts, run the specific script with a known input file rather than adding unrelated tooling.

## Documentation Expectations

- Keep design-facing rationale in `docs/`, `model/ozaki_subspace_model/docs/`, or `model/qe_band_solver_model/docs/`, not buried in source comments.
- When behavior changes, update the corresponding validation note if the command, metric, or conclusion changes.
- Prefer documenting reproducible commands with absolute or workspace-relative paths.

## Current Project Priorities

- The handoff document indicates the most important open work is algorithm freezing, not rebuilding the QE dataset from scratch.
- Generalized Hermitian eigensolver work and Ozaki/CRT design decisions are the current mainline topics.
- Avoid spending time on unrelated refactors unless they unblock the requested task.

## Plan Agent Usage Guidelines

### Problem
Plan agent can timeout (30min+) on large complex tasks without visible progress, causing poor user experience.

### Solutions

1. **Segmented Planning**: Call plan agent for ONE phase at a time, not the entire project
   - Good: "Plan Phase 1: SystemC backend implementation"
   - Bad: "Plan all 5 waves of the entire DSE framework"

2. **Background Execution**: Use `run_in_background=true` for plan agent
   - Continue other work while plan agent runs
   - Check results when system notification arrives

3. **Small Granularity**: Each plan should cover 1-2 specific tasks
   - Good: "Plan the SystemC output parser implementation"
   - Bad: "Plan the entire 3-layer DSE framework"

4. **Session Continuity**: Use `task_id` for follow-up questions
   - First call: `task(subagent_type="plan", ...)` → returns task_id
   - Follow-up: `task(task_id="...", prompt="clarify X")`
   - Saves 70%+ tokens vs starting fresh

5. **Fallback Strategy**: If plan agent times out twice, switch to:
   - Direct implementation with oracle consultation
   - Self-planning based on existing patterns
   - Ask user for priority clarification

### Example Workflow
```python
# Step 1: Plan current phase only
task(subagent_type="plan", run_in_background=true, prompt="Plan Phase X: [specific task]")

# Step 2: Continue other work while waiting
# (edit files, run tests, etc.)

# Step 3: When notification arrives, collect results
background_output(task_id="...")

# Step 4: Execute planned tasks
# (direct implementation or delegate to category agents)
```

## AGENTS.md Hierarchy

This repository uses hierarchical AGENTS.md files:
- **Root** (`./AGENTS.md`): Project overview, quick navigation, global conventions
- **Domain** (`docs/AGENTS.md`, `model/AGENTS.md`): Cross-cutting guidance for major directories
- **Specialist** (`docs/architecture/AGENTS.md`, `docs/benchmarks/AGENTS.md`, `model/ozaki_subspace_model/AGENTS.md`, `model/qe_band_solver_model/AGENTS.md`): Detailed domain-specific instructions
- **Integration** (`gem5_integration/AGENTS.md`, `dse_v2/AGENTS.md`, `runtime_api/AGENTS.md`, `Survey/AGENTS.md`): Component-specific guides

Child AGENTS.md files never repeat parent content. Navigate up the hierarchy for shared conventions.

## Good Agent Behavior In This Repo

- Read `docs/overview/agent_handoff_20260312.md` before making large design or documentation changes.
- Preserve existing numerical contracts and reported metrics.
- Make focused edits, then run the smallest relevant build or evaluator.
- In final reports, mention exactly which executable or script you ran and which file paths you changed.
