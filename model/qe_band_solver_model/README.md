# QE / CP2K / VASP-facing host-managed full-SCF system demo

This directory contains a **timed-functional TLM-style/SystemC-style demo** for a **DFT hybrid system model**.

## Scope

Implemented behavior-level flow:

`DFTHybridSystem -> HostSCF (CPU runtime) -> FPGAOrchestrator (thin device runtime) -> ChipTop -> EpisodeController -> ClusterGraphExecutor -> Cluster A/B/C/D -> next SCF iteration`

The current promoted model treats the old replay/body path as a legacy compatibility layer and exposes a **host-device-first control contract**:

- `ResidentSetDesc`
- `BandBatchDesc`
- `ScfIterationRequest`
- `DiagPolicy`
- `CompletionSummary`

Those public objects are then mapped into the existing internal hardware execution path:

- `EpisodeDescriptor -> EpisodeControllerState -> EpisodeResult`
- a persistent episode controller that owns workload bucket, resident-fit, FIFO-credit, spill, and diag-mode decisions
- a `ClusterGraphExecutor` that drives:
  - `Cluster A`: fused `h_psi + s_psi` operator sweep
  - `Cluster B`: reduced `H_sub / S_sub` build
  - `Cluster C`: hardware-first diagonalization proxy
  - `Cluster D`: refresh / residual -> `P_next`
- a single top-level `DFTHybridSystem` object;
- software-family selection for `QE`, `CP2K/QS_DIAG`, `CP2K/QS_OT`, `VASP/BLOCKED_DAVIDSON`, and `VASP/FAST`-style flows.

In addition, the runnable model now has a **bootstrap architecture-family layer** for system-level DSE:

- `F1` — Host-heavy / single-hotpath
- `F2` — Balanced hybrid / multi-operator pipeline
- `F3` — Device-heavy / full inner-loop offload

These family tags currently steer request/runtime policy, diag/offload defaults, resident-budget scaling, and reporting fields. They are the phase-1 scaffold for the later multi-family DSE harness.

This demo is still **not a numerically faithful DFT implementation**. It is a **host-managed timed-functional system model** that preserves `Host CPU -> thin device runtime -> hardware datapath` boundaries, models control plus DMA/completion traffic, and keeps `Cluster A/B/C/D` as an internal hardware realization instead of the public API.

## QE shell-stage view

For the `QE / CBANDS_DIAG` path, the current model still closes the same shell contract:

- `rho -> Veff`
- `while bands not converged { h_psi, s_psi, build H_sub / S_sub, cdiaghg, refresh / residual -> P_next }`
- `psi -> rho_out`
- `mix_rho / convergence gate`

What changed is the system contract:

- `HostSCF` now owns `rho -> Veff`, outer `SCF` control, `mix_rho`, convergence, and diag fallback policy
- `FPGAOrchestrator` now behaves as a thin device runtime that manages resident preload, batch DMA, host-diag assist, and completion summaries
- `Interconnect` now models TLM-style control and DMA transactions instead of plain string-only channels
- `ChipTop` still reuses `Cluster A/B/C/D` as the inner hardware datapath

What remains as the internal execution anchor:

- `h_psi` + `s_psi` now live under `Cluster A`
- `build H_sub / S_sub` now lives under `Cluster B`
- `cdiaghg` now has an explicit hardware-first `Cluster C` proxy instead of being split out of `VectorDiagCompanion`
- `refresh / residual -> P_next` now has an explicit `Cluster D`
- `psi -> rho_out / rho -> Veff / mix_rho` are no longer the primary chip-side execution path; the old `BODY_04` runtime remains as legacy/phase-2 support code

## Modeling level

Current modeling-level judgement:

- `HostSCF` is now a **CPU-side control runtime**
- `FPGAOrchestrator` is now a **thin device runtime / bridge**
- `Interconnect` is now a **control + DMA + completion transaction model**
- `ChipTop` remains a **cluster-first timed-functional executor**
- `Cluster A/B` reuse the old Phase-B leaf modules as datapath blocks, but are no longer dispatched through `ReplayBundleExecutor`
- `Cluster C` is a standalone hardware-first diagonalization proxy
- `Cluster D` is a standalone refresh/residual cluster instead of a host-side accounting split
- the legacy `BODY_04` and `BODY_10` code remains in-tree, but it is no longer the main executable path

In short, this directory should be read as:

> a host-managed `QE / CP2K / VASP` full-SCF runnable model with explicit CPU/device/data-movement contracts and an internal `Cluster A/B/C/D` hardware datapath,
> not as a numerically faithful DFT solver or a frozen RTL-level chip model.

## Top-level modules

- `DFTHybridSystem`
  - `Interconnect`
  - `ChipTop`
  - `FPGAOrchestrator`
    - `ChipTop::run_episode(EpisodeDescriptor)`
      - `EpisodeController`
      - `ClusterGraphExecutor`
        - `ClusterAOperatorSweep`
        - `ClusterBReducedBuild`
        - `ClusterCHardwareDiag`
        - `ClusterDRefreshResidual`
  - `HostSCF`

## On-chip partition used in the current demo

- **Control plane**
  - `CommandScheduler`
  - `ResidentContextController`
- **CIM projector chain**
  - `ContextLoader`
  - `DigitSerialInputBoundary`
  - `ConjugateSignSelector`
  - `NearSRAMCoeffBuffer`
  - `NearSRAMRowBuffer`
  - `CIMArrayCore`
    - `Residue3MCore`
    - `CoefficientAccumulator`
    - `RowMergeTree`
- **Near-memory but not necessarily CIM**
  - `NearSRAMSupport`
  - `NearMemoryDomain`
- **Digital companions**
  - `ReductionClosureEngine`
  - `VectorDiagCompanion`
  - `FFTCompanion`
- **Runtime-managed outer-update bundles**
  - `ReplayBundleExecutor`
  - `Body04FamilyController`
    - `OuterUpdateRuntimeDomain`
      - `DensityAccumulationStage`
        - `DensityAccumulatorUnit`
        - `DensityCommitUnit`
      - `PotentialRefreshStage`
        - `PotentialFieldUnit`
        - `ProjectorStateUpdater`
      - `MixingConvergenceStage`
        - `DensityMixerUnit`
        - `ConvergenceTracker`
  - `Body10FamilyController`
    - `PreconditionedUpdateVector`
    - `WaveCandidateCommit`
    - `OrthogonalizeUnit`
    - `RebindCommit`
    - `HistoryIntegrator`
    - `OTSummaryCommit`

## Files

- `sc_main.cpp` — executable entry with env-configured software/flow selection
- `src/dft_hybrid_system.*` — explicit full-system top module
- `include/types.hpp` — current type home for the host-device-first public objects (`ResidentSetDesc`, `BandBatchDesc`, `ScfIterationRequest`, `DiagPolicy`, `CompletionSummary`), the internal cluster-first types (`EpisodeDescriptor`, `EpisodeResult`, `SCFRunReport`, etc.), and the retained legacy replay/body types
- `src/episode_controller.*` — persistent cluster-first controller
- `src/cluster_graph_executor.*` — ordered A/B/C/D executor
- `src/cluster_a_operator_sweep.*` — fused operator-sweep cluster
- `src/cluster_b_reduced_build.*` — reduced-matrix build cluster
- `src/cluster_c_hardware_diag.*` — hardware-first diagonalization proxy
- `src/cluster_d_refresh_residual.*` — refresh / residual -> `P_next` cluster
- `src/replay_bundle_executor.*`, `src/body04_family_controller.*`, `src/outer_update_runtime_domain.*`, `src/body10_family_controller.*` — retained legacy/runtime support path, no longer the primary runnable path
- `src/preconditioned_update_vector.*` — `BODY_10A` preconditioned update leaf block
- `src/wave_candidate_commit.*` — `BODY_10A` wave-candidate commit leaf block
- `src/orthogonalize_unit.*` — `BODY_10B` orthogonalize leaf block
- `src/rebind_commit.*` — `BODY_10B` rebound-wave/projector commit leaf block
- `src/history_integrator.*` — `BODY_10C` history integration leaf block
- `src/ot_summary_commit.*` — `BODY_10C` summary export leaf block
- `src/interconnect.*` — control / DMA / completion transaction abstraction with TLM-style `b_transport`
- `src/host_scf.*` — CPU-side SCF driver and host-managed request generator
- `src/fpga_orchestrator.*` — thin device runtime that manages resident reuse, DMA, and host-diag fallback
- `src/chip_top.*` — on-chip Phase-B replay facade
- `src/density_accumulation_stage.*` — `Phase C / sum_band` stage wrapper
- `src/density_accumulator_unit.*` — density reduction block inside `Phase C`
- `src/density_commit_unit.*` — density-object commit block inside `Phase C`
- `src/potential_refresh_stage.*` — `Phase D / v_of_rho/newd` stage wrapper
- `src/potential_field_unit.*` — potential-field build block inside `Phase D`
- `src/projector_state_updater.*` — projector-state update block inside `Phase D`
- `src/mixing_convergence_stage.*` — `Phase E / mix_rho` / convergence gate stage wrapper
- `src/density_mixer_unit.*` — density-mix block inside `Phase E`
- `src/convergence_tracker.*` — convergence/history block inside `Phase E`
- `src/command_scheduler.*`
- `src/resident_context_controller.*`
- `src/context_loader.*`
- `src/digit_serial_input_boundary.*`
- `src/conjugate_sign_selector.*`
- `src/near_sram_coeff_buffer.*`
- `src/near_sram_row_buffer.*`
- `src/cim_array_core.*`
- `src/residue_3m_core.*`
- `src/coefficient_accumulator.*`
- `src/row_merge_tree.*`
- `src/cim_eligible_operator_subchain.*`
- `src/near_sram_support.*`
- `src/near_memory_domain.*`
- `src/reduction_closure_engine.*`
- `src/vector_diag_companion.*`
- `src/fft_companion.*`
- `include/systemc_compat.hpp` — fallback compatibility layer when a real SystemC library is unavailable

## Build

### Default fallback build

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j
```

### Optional real SystemC build

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build-systemc \
  -DQE_BAND_SOLVER_USE_SYSTEMC=ON \
  -DSYSTEMC_HOME=<your-systemc-prefix>
cmake --build model/qe_band_solver_model/build-systemc -j
```

## Run

### Default QE flow

```bash
./model/qe_band_solver_model/build/qe_band_solver_model
```

### CP2K diagonalization-style flow

```bash
QEBS_SOFTWARE_FAMILY=CP2K QEBS_FLOW_FAMILY=QS_DIAG \
./model/qe_band_solver_model/build/qe_band_solver_model
```

### CP2K OT-style flow with `BODY_10`

```bash
QEBS_SOFTWARE_FAMILY=CP2K QEBS_FLOW_FAMILY=QS_OT \
./model/qe_band_solver_model/build/qe_band_solver_model
```

### VASP blocked-Davidson-style flow

```bash
QEBS_SOFTWARE_FAMILY=VASP QEBS_FLOW_FAMILY=BLOCKED_DAVIDSON \
./model/qe_band_solver_model/build/qe_band_solver_model
```

### VASP fast mode-switch flow

```bash
QEBS_SOFTWARE_FAMILY=VASP QEBS_FLOW_FAMILY=FAST \
./model/qe_band_solver_model/build/qe_band_solver_model
```

### Optional env vars

- `QEBS_MAX_SCF_ITERS`
- `QEBS_ENABLE_FFT`
- `QEBS_SOFTWARE_FAMILY`
- `QEBS_FLOW_FAMILY`
- `QEBS_DEVICE_DIAG_MAX_DIM`
- `QEBS_FORCE_HOST_DIAG`
- `QEBS_ALLOW_CPU_DIAG_FALLBACK`
- `QEBS_ARCH_FAMILY`
- `QEBS_ASSUMPTION_SET_ID`
- `QEBS_OFFLOAD_SCOPE`
- `QEBS_RESIDENT_POLICY`
- `QEBS_CASE_ID`
- `QEBS_RESULT_JSON`

### Canonical candidate JSON export

The runnable model can emit a machine-readable candidate result JSON for the QE gold comparison lane and the architecture-family DSE sweep.

Example smoke runs:

```bash
mkdir -p tmp

QEBS_ARCH_FAMILY=F1 QEBS_MAX_SCF_ITERS=1 \
QEBS_CASE_ID=si8_pbe_nc \
QEBS_RESULT_JSON=./tmp/qebs_f1_candidate.json \
./model/qe_band_solver_model/build/qe_band_solver_model

QEBS_ARCH_FAMILY=F3 QEBS_MAX_SCF_ITERS=1 \
QEBS_CASE_ID=si8_pbe_nc \
QEBS_RESULT_JSON=./tmp/qebs_f3_candidate.json \
./model/qe_band_solver_model/build/qe_band_solver_model
```

`QEBS_RESULT_JSON` writes the canonical candidate payload, while `QEBS_CASE_ID` carries the workload identity into that JSON so it can be compared against normalized QE gold baselines.

### Canonical QE gold gate command

The formal QE gold gate currently freezes the canonical workload set `si8_pbe_nc` + `si8_pbe_uspp`, with `si8_pbe_nc` marked as the first-priority convergence case and `F1` fixed as the first convergence family.

Canonical gate command:

```bash
python3 docs/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --gold-required-only \
  --workloads si8_pbe_nc si8_pbe_uspp \
  --families F1 F2 F3 \
  --canonical-only \
  --execute-model \
  --auto-match-baseline-iters \
  --fail-on-gold-mismatch \
  --output-dir tmp/qe_gold_lane
```

Expected outputs under `tmp/qe_gold_lane/`:

- `systemc_architecture_family_dse_bootstrap_v0.json`
- `systemc_architecture_family_dse_bootstrap_v0.csv`
- `qe_gold_gate_summary_v0.json`
- `qe_gold_gate_summary_v0.md`
- `artifacts/baseline/*.gold.json`
- `artifacts/candidate/*.json`
- `artifacts/compare/*.compare.json`
- `artifacts/stdout/*.log`

Exit code contract:

- `0` only when every selected gold-required row is `pass`
- nonzero on any `mismatch` or infrastructure status (`baseline_missing`, `baseline_normalization_error`, `candidate_missing`, `model_error`, `compare_error`)

## Architecture Note

The host-device-first architecture writeup for this runnable model lives at:

- [/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/host_managed_full_scf_architecture_v1_20260409.md](/Volumes/remote/phd/year_2/project/dft加速/docs/architecture/host_managed_full_scf_architecture_v1_20260409.md)

## Phase-B Leaf Chains

Current `Phase B` is no longer just one abstract on-chip body. In the runnable model it is already split into three hardware-shaped leaf chains:

- `panel ingress chain`: `NearSRAMSupport.stage_panel -> FFTCompanion.Transform (optional) -> ContextLoader`
- `projector apply chain`: `DigitSerialInputBoundary -> ProjectConjugateSignSelector -> Residue3MCore.PROJECT -> CoefficientAccumulator -> NearSRAMCoeffBuffer -> BackprojectConjugateSignSelector -> Residue3MCore.BACKPROJECT -> RowMergeTree -> NearSRAMRowBuffer`
- `closure/update chain`: `NearSRAMSupport.aggregate -> ReductionClosureEngine.InputAssembler -> ReductionClosureEngine.HermitianClosureBuilder -> ReductionClosureEngine.SmallSolveFrontEnd -> VectorDiagCompanion.RitzUpdate`

These chains already carry explicit `accept / busy / complete`, queue-depth, route-backpressure, module-occupancy, and reference-cycle proxy summaries in the runtime logs.

## Expected behavior

A run prints timestamped logs that show:

1. `HostSCF` doing outer-shell `rho -> Veff` work on CPU
2. `HostSCF` issuing `ScfIterationRequest` with `ResidentSetDesc`, `BandBatchDesc`, and `DiagPolicy`
3. `Interconnect` showing control and DMA `b_transport` activity
4. `FPGAOrchestrator` preloading resident state, streaming the active batch, and launching device execution
5. `ChipTop` executing the internal hardware datapath:
   - panel staging in `NearSRAMSupport`
   - optional FFT transform in `FFTCompanion`
   - optional support-grid staging in `NearMemoryDomain`
   - `CommandScheduler` issuing row-block `LCW`
   - `ResidentContextController` binding resident contexts
   - `ContextLoader -> DigitSerialInputBoundary -> ConjugateSignSelector`
   - `CIMArrayCore.PROJECT -> NearSRAMCoeffBuffer -> CIMArrayCore.BACKPROJECT`
   - `RowMergeTree` / `NearSRAMRowBuffer` partial commit
   - local aggregation in `NearMemoryDomain`
   - reduced-space closure in `ReductionClosureEngine`
   - hardware-first diagonalization in `Cluster C`
   - refresh / residual update in `Cluster D`
6. When needed, the thin device runtime exporting reduced matrices to Host CPU, waiting for host-diag assist, and importing the diag solution back
7. `FPGAOrchestrator` emitting `CompletionSummary`
8. `HostSCF` consuming the returned wave/update objects and continuing `mix_rho / convergence`
10. For `BODY_10`, `PreconditionedUpdateVector / WaveCandidateCommit`, `OrthogonalizeUnit / RebindCommit`, and `HistoryIntegrator / OTSummaryCommit` run in sequence
11. Inside `BODY_04`, `DensityAccumulatorUnit / DensityCommitUnit`, `PotentialFieldUnit / ProjectorStateUpdater`, and `DensityMixerUnit / ConvergenceTracker` run in sequence
12. Host collecting a per-iteration report and final `DFTRunReport`
13. Either the next SCF iteration starts or the run stops after convergence / iteration cap

## Notes

- The current smoke run uses the fallback compatibility layer because no real SystemC library was available in the environment.
- The code is organized to preserve host/FPGA/chip transaction boundaries while making the whole system object explicit.
- The current model explicitly tracks `object handle`, `version`, `resident buffer tag`, `resident_context_id`, `resident_generation`, `ReplayBundleDescriptor/ReplayBundleCompletion`, `Body10LoweringPlan`, `Body04LoweringPlan`, `lcw_words_issued`, `row_blocks_processed`, `BODY_10` bundle identity, and `BODY_04` bundle identity.
- `DFTRunReport` now also exposes run-level `lcw` total, `row_block` total, `Phase B` / `BODY_10` / `BODY_04` reference-cycle and backpressure totals, per-family data-movement totals, and `convergence_reason`.
- `QE` remains the only executed software anchor in the workspace; `CP2K` and `VASP` are still behavior-level mappings grounded by source/document reconstruction rather than local executable evidence.
