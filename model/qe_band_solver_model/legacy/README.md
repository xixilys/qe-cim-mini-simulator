# Archived replay/body compatibility subtree

This directory stores the legacy replay/body compatibility implementation that used to live in the main
`model/qe_band_solver_model/src` and `include` directories.

## Why it was moved

The promoted runnable path is now:

`sc_main -> DFTHybridSystem -> HostSCF -> FPGAOrchestrator -> ChipTop -> ClusterGraphExecutor -> Cluster A/B/C/D`

The files in this `legacy/` subtree are **not part of the default build anymore**. They are kept as archived
compatibility/runtime support code because:

- older design docs still discuss the `BODY_04` / `BODY_10` family path
- `include/types.hpp` still preserves the corresponding descriptor/report types
- the archived code remains useful as a reference for future contract-decoupling or replay-path revival work

## Contents

- `include/replay_bundle_executor.hpp`, `src/replay_bundle_executor.cpp`
- `include/body04_family_controller.hpp`, `src/body04_family_controller.cpp`
- `include/outer_update_runtime_domain.hpp`, `src/outer_update_runtime_domain.cpp`
- `include/body10_family_controller.hpp`, `src/body10_family_controller.cpp`
- `BODY_04` stage/unit files:
  - `density_accumulation_stage.*`
  - `density_accumulator_unit.*`
  - `density_commit_unit.*`
  - `potential_refresh_stage.*`
  - `potential_field_unit.*`
  - `projector_state_updater.*`
  - `mixing_convergence_stage.*`
  - `density_mixer_unit.*`
  - `convergence_tracker.*`
- `BODY_10` stage/unit files:
  - `preconditioned_update_vector.*`
  - `wave_candidate_commit.*`
  - `orthogonalize_unit.*`
  - `rebind_commit.*`
  - `history_integrator.*`
  - `ot_summary_commit.*`

## Rules for future cleanup

- Do not delete this subtree blindly just because it is not compiled by default.
- First update any docs/contracts that still reference these files as current implementation anchors.
- If the archive is eventually removed, that should be a separate verified cleanup slice.
