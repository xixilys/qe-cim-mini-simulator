# QE / CP2K / VASP-facing full-SCF system demo

This directory contains a **timed-functional SystemC-style demo** for a **DFT hybrid system model**.

## Scope

Implemented behavior-level flow:

`DFTHybridSystem -> HostSCF -> FPGAOrchestrator -> ReplayBundleExecutor -> {ChipTop Phase B, optional BODY_10A/B/C under BODY_10_FAMILY, Body04FamilyController -> OuterUpdateRuntimeDomain} -> next SCF iteration`

The promoted model keeps the existing **Phase B band-solver episode subsystem** as the core on-chip body, but now also models:

- a unified `ReplayBundleDescriptor -> ReplayBundleCompletion` runtime path;
- a runtime-managed `BODY_04` family bundle with frozen `BODY_04A/B/C` sub-body catalog for outer update stages;
- an explicit `OuterUpdateRuntimeDomain` with a `Body04LoweringPlan`;
- a runtime-managed `BODY_10` family bundle with frozen `BODY_10A/B/C` sub-body catalog plus explicit `Body10StageRequest / Body10StageSummary / Body10LoweringPlan` for `CP2K/QS_OT`-style orbital-update extension;
- a single top-level `DFTHybridSystem` object;
- software-family selection for `QE`, `CP2K/QS_DIAG`, `CP2K/QS_OT`, `VASP/BLOCKED_DAVIDSON`, and `VASP/FAST`-style flows.

Current phase interpretation:

- `Phase A` = setup / seed / object bind
- `Phase B` = `BODY_01/BODY_02/BODY_03` on-chip replay bundle
- `Phase Bx` = optional `BODY_10A/B/C` inside runtime-managed `BODY_10` family
- `Phase C/D/E` = `BODY_04A/B/C` inside runtime-managed `BODY_04` family bundle
- `Phase E exit` = `BODY_04C` convergence gate back to `BODY_05`

This demo is still **not a numerically faithful DFT implementation**. It is a **system-level control / object-lifecycle model** that preserves the `Host -> FPGA/runtime -> Chip` transaction boundaries while extending the flow beyond one isolated band-solver episode. The current version emits an explicit `DFTRunReport` with per-iteration `Phase B`, optional `BODY_10`, and `BODY_04` bundle summaries, plus run-level `lcw`, `row_block`, data-movement, convergence-reason totals, `Phase B` reference-cycle/backpressure totals, and `BODY_04` reference-cycle/backpressure totals.

## Modeling level

Current modeling-level judgement:

- `Host/FPGA/runtime` remains mainly **transaction/object-level**, while `BODY_10` is now a runtime-managed timed-functional subchain with explicit leaf modules `PreconditionedUpdateVector`, `WaveCandidateCommit`, `OrthogonalizeUnit`, `RebindCommit`, `HistoryIntegrator`, and `OTSummaryCommit`, plus stage-level summaries and leaf-block flow-control proxies;
- `ChipTop Phase B` is now a **structured timed-functional model with a leaf-block `L2 proxy` flow-control layer**;
- `OuterUpdateRuntimeDomain / BODY_04` is now also a **structured timed-functional runtime-domain model with leaf-block `L2 proxy` flow-control** across `DensityAccumulatorUnit`, `DensityCommitUnit`, `PotentialFieldUnit`, `ProjectorStateUpdater`, `DensityMixerUnit`, and `ConvergenceTracker`;
- together they carry explicit `module occupancy`, `critical_domain` or `critical_stage`, `reference-cycle` busy totals, leaf-block queue depth, `accept/busy/complete`, ingress/egress ownership, arbitration domain, and dominant backpressure route or stage;
- the system is **not yet** a finished hardware microarchitecture model because queue depths, arbitration policy, cross-body overlap, and chip-visible lowering boundaries are still provisional rather than frozen silicon contracts.

In short, this directory should be read as:

> a `QE`-connected full-SCF system model with hardware-shaped module boundaries, Phase-B and BODY-04 structural timing summaries, and leaf-block `L2` flow-control proxies across the band-solver and outer-update subchains,
> not as a numerically faithful DFT solver or a frozen RTL-level chip model.

## Top-level modules

- `DFTHybridSystem`
  - `Interconnect`
  - `ChipTop`
  - `FPGAOrchestrator`
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
- `src/types.hpp` — transaction / object / resident-context / bundle structs, including `ReplayBundleDescriptor`, `ReplayBundleCompletion`, `Body10StageRequest`, `Body10PrecondStats`, `Body10PrecondSummary`, `Body10OrthoStats`, `Body10OrthoSummary`, `Body10HistoryStats`, `Body10HistorySummary`, `Body10StageSummary`, `Body10LoweringPlan`, `Body04StageRequest`, `SCFIterationReport`, and `DFTRunReport`
- `src/replay_bundle_executor.*` — unified runtime replay-bundle executor
- `src/body04_family_controller.*` — runtime-managed `BODY_04` family facade
- `src/outer_update_runtime_domain.*` — explicit outer-update runtime domain and lowering-plan owner
- `src/body10_family_controller.*` — runtime-managed `BODY_10` OT/block-update controller with explicit stage/lowering summaries
- `src/preconditioned_update_vector.*` — `BODY_10A` preconditioned update leaf block
- `src/wave_candidate_commit.*` — `BODY_10A` wave-candidate commit leaf block
- `src/orthogonalize_unit.*` — `BODY_10B` orthogonalize leaf block
- `src/rebind_commit.*` — `BODY_10B` rebound-wave/projector commit leaf block
- `src/history_integrator.*` — `BODY_10C` history integration leaf block
- `src/ot_summary_commit.*` — `BODY_10C` summary export leaf block
- `src/interconnect.*` — host/FPGA/chip channel abstraction
- `src/host_scf.*` — outer SCF driver
- `src/fpga_orchestrator.*` — runtime orchestration for Phase B, `BODY_10`, and `BODY_04`
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
- `src/systemc_compat.hpp` — fallback compatibility layer when a real SystemC library is unavailable

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

## Phase-B Leaf Chains

Current `Phase B` is no longer just one abstract on-chip body. In the runnable model it is already split into three hardware-shaped leaf chains:

- `panel ingress chain`: `NearSRAMSupport.stage_panel -> FFTCompanion.Transform (optional) -> ContextLoader`
- `projector apply chain`: `DigitSerialInputBoundary -> ProjectConjugateSignSelector -> Residue3MCore.PROJECT -> CoefficientAccumulator -> NearSRAMCoeffBuffer -> BackprojectConjugateSignSelector -> Residue3MCore.BACKPROJECT -> RowMergeTree -> NearSRAMRowBuffer`
- `closure/update chain`: `NearSRAMSupport.aggregate -> ReductionClosureEngine.InputAssembler -> ReductionClosureEngine.HermitianClosureBuilder -> ReductionClosureEngine.SmallSolveFrontEnd -> VectorDiagCompanion.RitzUpdate`

These chains already carry explicit `accept / busy / complete`, queue-depth, route-backpressure, module-occupancy, and reference-cycle proxy summaries in the runtime logs.

## Expected behavior

A run prints timestamped logs that show:

1. `BODY_05` outer-SCF setup and `BODY_00` object binding
2. Host lowering each iteration into `ReplayBundleDescriptor`
3. `FPGAOrchestrator` forwarding replay bundles to `ReplayBundleExecutor`
4. For `Phase B`, `ReplayBundleExecutor` dispatching `BODY_01/BODY_02/BODY_03` into `ChipTop`
5. `ChipTop` executing:
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
   - residual/update in `VectorDiagCompanion`
6. For `CP2K/QS_OT`, `ReplayBundleExecutor` dispatching the runtime-managed `BODY_10` bundle
7. `ReplayBundleExecutor` dispatching the runtime-managed `BODY_04` family bundle
8. `Body04FamilyController` forwarding into `OuterUpdateRuntimeDomain`
9. `OuterUpdateRuntimeDomain` emitting `Body04LoweringPlan` and then running `DensityAccumulationStage -> PotentialRefreshStage -> MixingConvergenceStage`
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
