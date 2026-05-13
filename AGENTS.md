# AGENTS Guide

## Purpose

This repository is a **generic DSE + multi-level simulation prototype** for heterogeneous accelerators.  The active work is design-space exploration, promotion across L1/L2/L3/L4 fidelity, generic SystemC-style timing simulation, and gem5 GenericAccel descriptor/request/microarchitecture/completion evidence.

QE/DFT/Ozaki material is no longer the mainline. Historical application-specific material has been removed from the active working tree; restore only explicitly needed reference files from git history.

## Active layout

```
.
├── dse_v2/                         # DSE orchestration, workload IR, mapping, evidence, reports
├── model/generic_sim_backend/       # Generic JSON-driven simulator executable: generic_sim
├── gem5_integration/                # GenericAccel gem5 model, configs, L4 driver
├── runtime_api/                     # Domain-neutral C offload/proxy ABI
├── docs/                            # Current generic design/runbook docs
└── tools/                           # Supporting local analysis tools, when present
```

## Quick navigation

- DSE implementation: `dse_v2/AGENTS.md`
- Generic simulator: `model/AGENTS.md` and `model/generic_sim_backend/README.md`
- gem5 L4 path: `gem5_integration/AGENTS.md`
- Architecture docs: `docs/architecture/AGENTS.md`
- Benchmark/evidence docs: `docs/benchmarks/AGENTS.md`
- Runtime proxy ABI: `runtime_api/AGENTS.md`

## Build and validation

```bash
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j
python3 -m pytest -q dse_v2/tests
python3 dse_v2/scripts/dse/run_full_flow_pilot.py --backend systemc --out runs/dse/generic_systemc_pilot
```

For C++ simulator edits, rebuild `model/generic_sim_backend/build/generic_sim` and run `ctest --test-dir model/generic_sim_backend/build --output-on-failure` when tests are built.

For Python DSE edits, run the smallest relevant `dse_v2/tests` target, then `python3 -m compileall dse_v2` if imports changed.

## Workspace rules

- Do not modify external upstream workspaces such as `/Users/xixilys/project/qe-7.5`.
- Do not recreate historical application-specific directories unless the task explicitly requires a scoped reference fixture.
- Expect a dirty working tree.  Do not revert unrelated user changes.
- Avoid committing generated caches, local simulator builds, gem5 m5out directories, and scratch `tmp*/` outputs.

## Style

- Python: 4 spaces, standard library first, explicit error returns for CLI scripts.
- C++: C++17, direct loops are fine, keep simulator contracts JSON-visible and testable.
- Keep core names domain-neutral: workload family, compute graph, adapter, mapping, evidence, simulator, descriptor.
- If a domain-specific adapter is needed, keep it out of core IR and mark claim boundaries explicitly.
