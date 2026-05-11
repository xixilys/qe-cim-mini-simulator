# QE CIM Mini Simulator

System-level prototype and design notes for accelerating Quantum ESPRESSO
subspace diagonalization and related dense kernels with a CIM-oriented backend.

## Repository Scope

This repository currently contains:

- `model/`: model index plus two separate model stacks
- `model/ozaki_subspace_model/`: standalone Ozaki/CRT GEMM and iterative subspace evaluator stack
- `model/qe_band_solver_model/`: a timed-functional `c_bands` episode subsystem demo
- `docs/`: design notes, benchmark helpers, and minimal QE inputs

It intentionally excludes:

- vendored QE source trees
- raw QE runtime dumps
- temporary wavefunction / density files
- large benchmark archives and presentation artifacts

## Build

The simulator currently builds via:

```bash
make -C model/ozaki_subspace_model
```

This requires a working SystemC installation. The existing `Makefile` expects
headers and libraries to be reachable from a local toolchain configuration.

The merged `c_bands` subsystem demo can be built independently via:

```bash
cmake -S model/qe_band_solver_model -B model/qe_band_solver_model/build
cmake --build model/qe_band_solver_model/build -j
./model/qe_band_solver_model/build/qe_band_solver_model
```

## Key Design Files

Start with `docs/README.md`. It defines the current reading order and separates global design, implementation notes, runbooks, OpenSpec changes, and historical evidence.

For Generic DSE review, read:

- `docs/architecture/generic_dse_global_system_design_v0.md`: global design for the generic DSE + SystemC/gem5+SystemC evidence loop
- `docs/architecture/generic_dse_framework_design_spec_v2.md`: detailed DSE subsystem design
- `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md`: execution and evidence-review handbook
- `dse_v2/README.md`: implementation entry point
- `openspec/HANDBOOK.md`: OpenSpec governance and archive rules

For the original QE/CIM system review, the key files are:

- **System specs**
  - `docs/architecture/system_design_master_spec_v0.md`: canonical system-level master spec
  - `docs/architecture/system_interface_contract_v0.md`: `Host <-> FPGA/runtime <-> Chip` interfaces, route sets, and object-state contracts
  - `docs/architecture/system_exception_and_flow_control_contract_v0.md`: exception, queue, backpressure, and flow-control contracts
- **Control and replay**
  - `docs/control/long_control_word_isa_v0.md`: LCW vocabulary and control semantics
  - `docs/control/qe_cbands_lcw_lowering_v0.md`: `QE c_bands` lowering into LCW/replay form
  - `docs/control/qe_phase_cde_replay_bundle_contract_v0.md`: `BODY_04` replay-bundle contract
  - `docs/control/body10_ot_block_update_contract_v0.md`: `BODY_10` / `CP2K QS_OT` extension contract
- **CIM and near-memory**
  - `docs/cim/cim_macro_block_and_timing_v0.md`: CIM macro organization and timing-facing description
  - `docs/cim/cim_resident_context_and_near_sram_contract_v0.md`: resident-context and near-SRAM residency contract
  - `docs/cim/fused_digit_residue_multiply_flow_v0.md`: digit-serial / residue-domain compute flow
- **Runnable system model**
  - `model/qe_band_solver_model/README.md`: runnable model overview
  - `model/qe_band_solver_model/src/dft_hybrid_system.cpp`: hybrid `Host + FPGA/runtime + Chip` system object
  - `model/qe_band_solver_model/src/host_scf.cpp`: host-managed SCF control/runtime entry
  - `model/qe_band_solver_model/src/fpga_orchestrator.cpp`: thin device-runtime bridge
  - `model/qe_band_solver_model/src/clusters/cluster_graph_executor.cpp`: active `Cluster A/B/C/D` execution path
  - `model/qe_band_solver_model/legacy/README.md`: archived replay/body compatibility subtree
  - `model/qe_band_solver_model/include/types.hpp`: shared descriptors, reports, and object summaries
- **Context and evidence**
  - `docs/overview/project_development_timeline.md`: long-form project development record
  - `docs/overview/qe_project_implementation_architecture_and_plan_v0.md`: project-level implementation architecture, roadmap, workstreams, and validation gates
  - `docs/overview/agent_handoff_20260312.md`: current handoff and priority context
  - `model/qe_band_solver_model/docs/qe_band_solver_smoke_run_20260326.md`: current `QE` / `CP2K` smoke validation notes
  - `docs/README.md`: current documentation reading order

## Notes

- The code in `model/` is a prototype, not a drop-in QE plugin.
- The canonical long-form development record is in `docs/overview/project_development_timeline.md`.
- The merged `QE` band-solver SystemC overview is in `docs/architecture/qe_band_solver_systemc_overview_20260325.md`.
- The merged `QE` band-solver transaction semantics are in `docs/architecture/qe_band_solver_transaction_semantics_20260326.md`.
- The standalone evaluator stack is summarized in `model/README.md`.
- The generalized subspace behavioral validation flow is documented in `model/ozaki_subspace_model/docs/generalized_subspace_validation.md`.
- The full FP64 complex Ozaki-II emulation flow is documented in `model/ozaki_subspace_model/docs/complex_ozaki_fp64_validation.md`.
- The dedicated FP64 complex Ozaki-II executable is `model/ozaki_subspace_model/bin/complex_ozaki_eval`.
- QE-specific benchmark helpers and tiny example inputs are kept under `docs/`.
