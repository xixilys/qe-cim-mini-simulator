# Documentation Index

`docs/` now contains the **active generic DSE / TLM / SystemC / gem5 design documentation**.  Application-specific historical documents were removed from the active working tree.

## Current directories

- `docs/architecture/` — generic DSE architecture specs, reusable architecture templates, and system design notes.
- `docs/architecture/generic_dse/` — schema notes for design points, evaluation results, and promotion logic.
- `docs/benchmarks/` — generic simulation-system handbook and machine-readable schemas for workload/result exchange.

## Main entry points

1. `docs/architecture/generic_dse_framework_design_spec_v2.md`
2. `docs/architecture/generic_dse_global_system_design_v0.md`
3. `docs/architecture/generic_dse_architecture_catalog_p2.md`
4. `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md`
5. `docs/benchmarks/workload_ir_schema_v0.json`
6. `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json`

## Cleanup rule

Do not add application-specific runbooks, literature dumps, or one-off experiment outputs to active `docs/`.  Put historical/reference material in a clearly named future adapter/reference directory.
