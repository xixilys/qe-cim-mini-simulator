# Generic DSE + TLM/SystemC/gem5 Acceleration Prototype

This repository is now organized around a **domain-neutral design-space exploration flow** for heterogeneous accelerator systems.  The active mainline is not a QE/VASP-specific DFT codebase; old application-specific artifacts have been removed from the working tree.

## Active mainline

- `dse_v2/` — DSE orchestration, workload IR, mapping, promotion, evidence, reporting, and L1/L2/L3/L4 backend adapters.
- `model/generic_sim_backend/` — generic JSON-driven C++/SystemC-style timing backend (`generic_sim`).
- `gem5_integration/src/dev/generic_accel/` — GenericAccel gem5 device model and MMIO/descriptor path.
- `gem5_integration/test_programs/generic_accel/` — L4 guest driver for descriptor/request/microarchitecture/completion runs.
- `runtime_api/` — small domain-neutral C ABI for proxy offload programs.
- `docs/architecture/generic_dse*` and `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md` — current design docs and runbook.

## Removed legacy/reference material

Old QE/DFT/Ozaki/proxy documents, datasets, scripts, generated artifacts, and models were removed from the active working tree after review.  If a specific historical artifact is needed later, restore only that file from git history or an external backup, and keep it outside core DSE assumptions.

## Quick start

```bash
# Build generic simulator
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j

# Run Python tests for the active DSE stack
python3 -m pytest -q dse_v2/tests

# Run a full-flow pilot through the generic SystemC backend
python3 dse_v2/scripts/dse/run_full_flow_pilot.py \
  --backend systemc \
  --out runs/dse/generic_systemc_pilot
```

L4 evidence is claim-gated and requires a built gem5 binary, the GenericAccel config, and the generic L4 guest driver.  The trusted default path is the in-gem5 GenericAccel microarchitecture model; `generic_sim` is still required for L3 and for explicitly requested diagnostic fallback paths.

## Current cleanup boundary

Mainline docs/code should describe the generic DSE/TLM/SystemC/gem5 path.  Optional domain adapters may live under clearly named `reference_workloads/` or future adapter directories, but they must not define core IR, core schemas, or default project direction.
