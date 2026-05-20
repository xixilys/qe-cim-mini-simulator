# Documentation Index

`docs/` contains the **active generic DSE / TLM / SystemC / gem5 design documentation** plus scoped proof-path manuals.  The reusable docs remain workload-agnostic, and the current primary proof path is DFT/QE full-SCF hardware DSE through explicit reference workload/profile boundaries.

## Current directories

- `docs/architecture/` — generic DSE architecture specs, reusable architecture templates, and system design notes.
- `docs/architecture/generic_dse/` — schema notes for design points, evaluation results, and promotion logic.
- `docs/architecture/dft_scf_hardware_dse_design_manual.md` — active DFT/QE full-SCF hardware DSE proof-path manual.
- `docs/benchmarks/` — generic simulation-system handbook and machine-readable schemas for workload/result exchange.

## Main entry points

1. `docs/architecture/generic_dse_framework_design_spec_v2.md`
2. `docs/architecture/generic_dse_global_system_design_v0.md`
3. `docs/architecture/generic_dse_architecture_catalog_p2.md`
4. `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md`
5. `docs/architecture/dft_scf_hardware_dse_design_manual.md`
6. `docs/benchmarks/workload_ir_schema_v0.json`
7. `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`

## Cleanup rule

Do not add broad literature dumps or one-off experiment outputs to active `docs/`.  Scoped adapter/proof-path manuals are allowed when they preserve generic-core boundaries and fail-closed claim semantics.
