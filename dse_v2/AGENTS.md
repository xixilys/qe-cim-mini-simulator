# AGENTS Guide - dse_v2/

## Purpose

`dse_v2/` is the active generic design-space exploration stack.  It owns workload IR, profile/importer packaging, architecture mapping, promotion, evidence generation, and reporting across L1/L2/L3/L4 fidelity.

## Main modules

- `core/ir/` — domain-neutral compute graph and task graph IR.
- `core/workload/` — workload package, profile/importer registry, workflow descriptors, graph lowering.
- `architecture/`, `core/architecture/` — architecture families and accelerator descriptions.
- `mapping/` — candidate mapping and selection workflows.
- `models/fast/`, `models/mid/` — L1 analytical and L2 Python TLM models.
- `backends/generic_systemc_bridge.py` — L3 generic simulator bridge.
- `backends/gem5_systemc_adapter.py` — L4 gem5+SystemC evidence adapter.
- `evidence/`, `reporting/`, `registry/` — auditable artifacts and experiment tracking.
- `reference_workloads/` — optional reference workload fixtures; not core schema.

## Commands

```bash
python3 -m pytest -q dse_v2/tests
python3 -m compileall dse_v2
python3 dse_v2/scripts/dse/run_full_flow_pilot.py --backend systemc --out runs/dse/generic_systemc_pilot
```

## Rules

- Core IR and schemas must stay domain-neutral.
- Optional workload importers must declare claim boundaries and required coverage through workflow metadata.
- Do not make a reference importer mandatory for generic DSE execution.
- L3/L4 evidence must use `model/generic_sim_backend` and `gem5_integration/src/dev/generic_accel`.
- Generated results belong under `runs/`, `tmp*/`, or ignored result directories, not active docs.
