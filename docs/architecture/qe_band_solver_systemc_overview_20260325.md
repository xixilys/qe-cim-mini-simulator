# 2026-03-25 SystemC model overview — QE band-solver / c_bands episode subsystem

## 1. Scope lock

This deliverable models only the **QE band-solver / `c_bands` episode subsystem**. It is **not** a full QE flow model.

Implemented runtime path:

`HostSCF(mock) -> FPGAOrchestrator -> ChipTop -> CIM Array Core / Near-SRAM Support Domain / Digital Companions -> episode complete -> Host rho update / convergence check`

The modeling style is **system-level / timed-functional / loosely timed**. Numeric values are mock values; the goal is to make the module boundaries, transaction semantics, and episode control flow explicit and runnable.

## 2. Code location

- `model/qe_band_solver_model/README.md`
- `model/qe_band_solver_model/sc_main.cpp`
- `model/qe_band_solver_model/src/*.hpp/*.cpp`

## 3. Architectural mapping used in code

### Host layer
- `HostSCF`
- Responsibility: start one `c_bands episode`, receive summary, perform mock `rho update / convergence check`

### FPGA layer
- `FPGAOrchestrator`
- Responsibility: episode orchestration, dispatch, batching/control glue, result collection

### Chip layer
- `ChipTop`
- Responsibility: compose the three explicit chip-side classes below

#### 3.1 CIM-eligible
- `CIMArrayCore`
- `CIMEligibleOperatorSubchain`
- Role: represent the operator tiles that are most natural to map toward a CIM-centered backend in v1+

#### 3.2 Near-memory but not necessarily CIM
- `NearSRAMSupport`
- `NearMemoryDomain`
- Role: resident panel staging and local aggregation around the CIM array core

#### 3.3 Digital companions
- `ReductionClosureEngine`
- `VectorDiagCompanion`
- `FFTCompanion`
- Role: closure / solve / residual-update / FFT-style support transactions that are control-friendly and not all required to be CIM

**Important correction retained in code:** `precision` is a constraint carried in `EpisodeConfig`; it is **not** used as the classification rule for modules.

## 4. Core transaction/data structs

The code defines these required structs in `src/types.hpp`:

- `EpisodeConfig`
- `WavePanel`
- `PartialHS`
- `FullHS`
- `ReducedMatrices`
- `RitzResult`
- `ResidualPacket`
- `SCFState`
- `EpisodeSummary` (extra summary wrapper for return path)

## 5. Executed demo flow

One demo run performs the following closed loop:

1. `HostSCF` creates one `c_bands episode` request.
2. `Interconnect` models host→FPGA latency.
3. `FPGAOrchestrator` performs episode dispatch and control glue.
4. `Interconnect` models FPGA→chip latency.
5. `ChipTop` runs several local micro-iterations:
   - `NearMemoryDomain` / `NearSRAMSupport` stage panels
   - optional `FFTCompanion` transforms panel data
   - `CIMEligibleOperatorSubchain` dispatches tiles into `CIMArrayCore`
   - `NearMemoryDomain` aggregates `PartialHS` into `FullHS`
   - `ReductionClosureEngine` forms `ReducedMatrices`
   - `VectorDiagCompanion` emits mock `et/evc` plus residual/update
6. `ChipTop` marks `episode done` and returns a summary.
7. `Interconnect` models chip→FPGA and FPGA→host return traffic.
8. `HostSCF` performs mock `rho update / convergence check`.

## 6. Environment decision

This deliverable is now merged into the main repository under `model/qe_band_solver_model`.

A real SystemC library was not available in the environment, so the smoke-tested path uses the fallback compatibility layer in `src/systemc_compat.hpp`. The naming and module structure remain SystemC-compatible enough for later migration.

## 7. Build / run

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j
./model/qe_band_solver_model/build/qe_band_solver_model
```

## 8. Future upgrade points

1. Swap the internals of `CIMArrayCore` with a stronger CIM-style operator engine without changing host/FPGA/chip episode semantics.
2. Replace scalar mock values with panel/tile traces sourced from a higher-fidelity kernel model.
3. Add multiple k-point / band batches in `FPGAOrchestrator`.
4. Insert richer resident-state and memory-capacity modeling inside `NearSRAMSupport`.
5. Split digital companion timing into finer control/compute subtransactions when moving beyond v0.
