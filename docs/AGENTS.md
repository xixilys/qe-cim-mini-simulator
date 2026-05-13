# AGENTS Guide - docs/

## Scope

`docs/` is for active generic DSE, architecture, benchmark/evidence, and simulation-interface documentation.  It should not be the dumping ground for historical app-specific experiments or broad literature dumps.

## Directory roles

- `architecture/`: system architecture specs, architecture templates, catalog docs, generic DSE design notes.
- `architecture/generic_dse/`: schema/rationale notes for design points, evaluation results, and promotion.
- `benchmarks/`: generic DSE runbook and JSON schemas for workload/result contracts.

## Rules

- Keep docs domain-neutral unless explicitly documenting an optional adapter.
- Keep historical or application-specific material out of the active tree unless explicitly restoring a scoped reference fixture.
- Prefer reproducible commands and workspace-relative paths.
- JSON files in active docs must be schemas, templates, or catalogs with an obvious consumer.
- Do not store generated benchmark results in active docs; use `runs/`, `tmp*/`, or a scoped evidence directory.

## Validation

After schema edits:

```bash
python3 -m json.tool docs/benchmarks/workload_ir_schema_v0.json >/dev/null
python3 -m json.tool docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json >/dev/null
```
