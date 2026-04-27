# AGENTS Guide - QE Band Solver Model

## Purpose

SystemC timed-functional model of the QE-connected band-solver subsystem with 4-Cluster pipeline architecture. Provides system-level performance estimation for Host-FPGA-Chip co-design before RTL implementation.

**Key Features:**
- Host-FPGA transaction semantics with SCF loop orchestration
- 4-Cluster pipeline: A (operator sweep), B (reduced build), C (hardware diag), D (refresh/residual)
- Configurable architecture templates (F1/F2/F3)
- Cycle-approximate timing for control flow and data movement
- Integration with DSE framework for architecture exploration

## Build System

Uses **CMake** with optional SystemC integration:

- **Compiler**: C++17 standard required
- **SystemC**: Optional (controlled by `QE_BAND_SOLVER_USE_SYSTEMC` flag)
- **Build directory**: `build/` (out-of-source build)
- **Executable**: `qe_band_solver_model`

## Build Commands

### Standard Build (SystemC compatibility layer)
```bash
cd model/qe_band_solver_model
mkdir -p build && cd build
cmake ..
make -j4
```

### Build with Real SystemC
```bash
cd model/qe_band_solver_model
mkdir -p build && cd build
cmake -DQE_BAND_SOLVER_USE_SYSTEMC=ON -DSYSTEMC_HOME=/opt/homebrew ..
make -j4
```

### Clean Build
```bash
rm -rf model/qe_band_solver_model/build
```

## Run Commands

### Basic Execution
```bash
./model/qe_band_solver_model/build/qe_band_solver_model
```

### With Configuration File
```bash
./model/qe_band_solver_model/build/qe_band_solver_model --config path/to/config.json
```

### Environment Variables
- `QE_WORKLOAD`: Workload name (si4, si8, graphene, au_slab, sic32)
- `QE_ARCH_TEMPLATE`: Architecture template (F1, F2, F3)
- `QE_LOG_LEVEL`: Logging verbosity (0=silent, 1=info, 2=debug, 3=trace)

**Example:**
```bash
QE_WORKLOAD=si8 QE_ARCH_TEMPLATE=F2 QE_LOG_LEVEL=2 ./model/qe_band_solver_model/build/qe_band_solver_model
```

## Architecture Overview

### Module Hierarchy
```
sc_main (sc_main.cpp)
  └── DFTHybridSystem (dft_hybrid_system.cpp)
      ├── HostSCF (host_scf.cpp)
      │   └── SCF loop orchestration
      ├── FPGAOrchestrator (fpga_orchestrator.cpp)
      │   └── Host-FPGA transaction management
      └── ChipTop (chip_top.cpp)
          ├── EpisodeController (clusters/episode_controller.cpp)
          ├── ClusterGraphExecutor (clusters/cluster_graph_executor.cpp)
          ├── ClusterA_OperatorSweep (clusters/cluster_a_operator_sweep.cpp)
          ├── ClusterB_ReducedBuild (clusters/cluster_b_reduced_build.cpp)
          ├── ClusterC_HardwareDiag (clusters/cluster_c_hardware_diag.cpp)
          ├── ClusterD_RefreshResidual (clusters/cluster_d_refresh_residual.cpp)
          └── OnChip Components (onchip/*)
```

### 4-Cluster Pipeline

| Cluster | Function | Time % | Key Components |
|---------|----------|--------|----------------|
| **A** | Operator Sweep (h_psi, s_psi) | 68% | CIM Array, Ozaki-II GEMM, Blocked GEMM |
| **B** | Reduced Build (H_sub, S_sub) | 4% | Reduction Engine, Vector Accumulator |
| **C** | Hardware Diag (Eigensolver) | 23% | Generalized Hermitian Eigensolver |
| **D** | Refresh/Residual | 5% | Residual Computation, Context Refresh |

### Architecture Templates

- **F1**: Baseline 4-cluster with CIM Array
- **F2**: Balanced 4-cluster with Traditional FPGA GEMM
- **F3**: High-throughput with increased parallelism

## Key Source Files

### Top-Level
- `sc_main.cpp`: Entry point, simulation setup
- `dft_hybrid_system.cpp`: Top-level system container
- `host_scf.cpp`: Host CPU SCF loop orchestration
- `fpga_orchestrator.cpp`: Host-FPGA transaction manager
- `chip_top.cpp`: FPGA chip-level container

### Cluster Controllers (src/clusters/)
- `episode_controller.cpp`: Episode-level control flow
- `cluster_graph_executor.cpp`: Cluster graph execution engine
- `cluster_a_operator_sweep.cpp`: h_psi/s_psi operator sweep
- `cluster_b_reduced_build.cpp`: H_sub/S_sub reduction
- `cluster_c_hardware_diag.cpp`: Generalized eigensolver
- `cluster_d_refresh_residual.cpp`: Residual and refresh

### On-Chip Components (src/onchip/)
- `cim_array_core.cpp`: CIM Array with Ozaki-II GEMM
- `blocked_gemm_engine.cpp`: Blocked GEMM implementation
- `traditional_fpga_gemm_core.cpp`: Traditional FPGA GEMM baseline
- `reduction_closure_engine.cpp`: Reduction tree for H_sub/S_sub
- `resident_context_controller.cpp`: Persistent object management
- `command_scheduler.cpp`: On-chip command scheduling
- `near_memory_domain.cpp`: Near-memory compute domain

### Utilities
- `interconnect.cpp`: Inter-module communication
- `architecture_template.cpp`: Architecture configuration loader
- `systemc_compat.hpp`: SystemC compatibility layer
- `types.hpp`: Common type definitions
- `logging.hpp`: Logging utilities

## Validation Methodology

### Transaction Semantics
- Host-FPGA transactions validated against QE control flow
- SCF loop convergence behavior matches QE
- Episode boundaries and data dependencies preserved

### Timing Estimation
- **Control flow**: Cycle-accurate (state machine transitions)
- **Data movement**: Cycle-accurate (DMA, SRAM access)
- **Compute kernels**: Proxy formulas (CIM Array, Eigensolver)

### Accuracy Expectations
- **Relative speedup**: ±20% (proxy formula uncertainty)
- **Absolute cycles**: Requires RTL validation
- **Control overhead**: High confidence (cycle-accurate)

## Integration with DSE Framework

The model is invoked by `docs/benchmarks/run_systemc_architecture_family_dse_sweep.py`:

1. DSE generates architecture configuration JSON
2. Model loads configuration and workload parameters
3. Model executes timed-functional simulation
4. Model reports cycle counts and resource utilization
5. DSE collects results for Pareto analysis

## Common Workflows

### Run Single Workload
```bash
cd model/qe_band_solver_model/build
./qe_band_solver_model --workload si8 --arch F2
```

### Run DSE Sweep
```bash
python3 docs/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --component-catalog docs/benchmarks/qe_ic_component_catalog_system_level_v1.json \
  --graph-spec docs/benchmarks/qe_ic_graph_seed_system_level_v1.json \
  --output-dir tmp/dse_sweep_results
```

### Extract Timing Results
```bash
# Results are in DSE output directory
cat tmp/dse_sweep_results/compare/speedup_summary.json
```

### Validate Against CPU Baseline
```bash
# Compare against QE trace data
python3 docs/benchmarks/summarize_qe_subspace_trace.py \
  docs/benchmarks/results/qe_si8_trace.csv
```

## Testing Expectations

- **After editing cluster controllers**: Rebuild and run with known workload, verify cycle counts
- **After editing on-chip components**: Rebuild and run DSE sweep, verify resource utilization
- **After editing architecture templates**: Rebuild and run all workloads, verify speedup trends
- **After editing host orchestration**: Rebuild and verify SCF convergence behavior

## Code Style

- **C++17** standard
- **4-space indentation**
- **snake_case** for functions
- **UpperCamelCase** for types and SystemC modules
- **SystemC naming**: `SC_MODULE`, `SC_CTOR`, `SC_METHOD`/`SC_THREAD`
- **Explicit state machines** for control flow
- **Timed waits**: `wait(cycles, SC_NS)` for cycle-accurate timing

## Error Handling

- Validate configuration files on load
- Check workload parameters for consistency
- Report missing or invalid architecture templates
- Exit with nonzero code on simulation errors
- Log warnings for proxy formula usage

## Documentation

- Architecture design: `docs/architecture/qe_fpga_clustered_v1_architecture_model_v0.md`
- Implementation package: `docs/architecture/qe_fpga_clustered_v1_implementation_package_20260402.md`
- Cycle approximation: `docs/architecture/qe_fpga_clustered_v1_cycle_approx_baseline_rows_v0_20260403.md`
- Validation notes: `model/qe_band_solver_model/docs/`

## Known Limitations

### Proxy Formulas
- **CIM Array**: Uses analytical formula for cycle count (not cycle-accurate RTL)
- **Eigensolver**: Uses LAPACK operation count estimate (not hardware implementation)
- **Impact**: ±20% uncertainty in absolute speedup

### Missing Features
- **Ozaki-II Integration**: Standalone evaluator not yet integrated into SystemC model
- **Cycle-Accurate Compute**: Core compute units use proxy formulas
- **Power Modeling**: No power estimation in current model

### Workarounds
- Use relative speedup comparisons (less sensitive to proxy formula errors)
- Validate control flow and data movement separately
- Plan RTL validation for absolute performance claims

## Critical Rules

- Preserve transaction semantics when modifying orchestration
- Update cycle counts when changing control flow
- Document proxy formula assumptions
- Run DSE sweep after architecture changes
- Validate against CPU baseline after major changes

## Next Steps

- For algorithm validation: see `model/ozaki_subspace_model/AGENTS.md`
- For DSE framework: see `docs/benchmarks/AGENTS.md`
- For architecture design: see `docs/architecture/AGENTS.md`
- For system context: see root `AGENTS.md`

## Future Work

1. **Integrate Ozaki-II**: Replace proxy formula with validated engine from `ozaki_subspace_model`
2. **Cycle-Accurate Eigensolver**: Implement hardware eigensolver model
3. **Clock Frequency Modeling**: Add frequency estimation for CIM vs Traditional FPGA
4. **Power Estimation**: Add power models for resource utilization
5. **RTL Validation**: Validate timing estimates against synthesized RTL
