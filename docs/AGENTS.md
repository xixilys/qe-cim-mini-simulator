# AGENTS Guide - docs/

## Scope

`docs/` is for active generic DSE, architecture, benchmark/evidence, simulation-interface documentation, and scoped proof-path manuals.  The reusable system docs stay domain-neutral, while DFT/QE full-SCF material is allowed when it documents the active reference proof path and keeps its adapter/profile claim boundary explicit.

## Directory roles

- `architecture/`: system architecture specs, architecture templates, catalog docs, generic DSE design notes.
- `architecture/generic_dse/`: schema/rationale notes for design points, evaluation results, and promotion.
- `architecture/dft_scf_hardware_dse_design_manual.md`: DFT/QE full-SCF hardware DSE proof-path manual and evidence/claim-boundary guide.
- `benchmarks/`: generic DSE runbook and JSON schemas for workload/result contracts.

## Rules

- Keep reusable docs domain-neutral unless explicitly documenting a scoped adapter/profile/proof path.
- Keep historical or application-specific material out of the active tree unless explicitly restoring a scoped reference fixture or maintaining the active DFT/QE proof-path manual.
- Prefer reproducible commands and workspace-relative paths.
- JSON files in active docs must be schemas, templates, or catalogs with an obvious consumer.
- Do not store generated benchmark results in active docs; use `runs/`, `tmp*/`, or a scoped evidence directory.

## Validation

After schema edits:

```bash
python3 -m json.tool docs/benchmarks/workload_ir_schema_v0.json >/dev/null
python3 -m json.tool docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json >/dev/null
```
