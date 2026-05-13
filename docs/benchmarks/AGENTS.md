# AGENTS Guide - docs/benchmarks/

## Purpose

Benchmark docs define generic evidence, schema, and runbook contracts for DSE simulation flows.  Runnable tools should live outside docs.

## Active files

- `generic_dse_simulation_system_handbook_v1.md` — main runbook for L1/L2/L3/L4 evidence flow.
- `workload_ir_schema_v0.json` — generic workload IR exchange schema.
- `systemc_architecture_family_dse_result_schema_v0.json` — generic DSE result bundle schema.

## Rules

- Keep contracts generic and simulator-oriented.
- Do not add app-specific baseline acquisition plans here.
- Do not store generated traces/results under `docs/benchmarks/`.
- Legacy app-specific benchmark material belongs under `legacy/`.

## Validation

```bash
python3 -m json.tool docs/benchmarks/workload_ir_schema_v0.json >/dev/null
python3 -m json.tool docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json >/dev/null
```
