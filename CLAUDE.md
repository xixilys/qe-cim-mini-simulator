# CLAUDE Guide

Use this repository as a generic accelerator DSE workspace.

## Mainline scope

- DSE design-space exploration and evidence flow: `dse_v2/`
- Generic timing backend: `model/generic_sim_backend/`
- gem5 GenericAccel L4 path: `gem5_integration/src/dev/generic_accel/`, `gem5_integration/configs/generic_accel_l4_test.py`, `gem5_integration/test_programs/generic_accel/`
- Domain-neutral proxy ABI: `runtime_api/`
- Generic docs: `docs/architecture/generic_dse*`, `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md`

## Removed legacy material

QE/DFT/Ozaki-specific historical material has been removed from the active working tree. Do not recreate it or move it back without an explicit request.

## Useful commands

```bash
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j
python3 -m pytest -q dse_v2/tests
python3 dse_v2/scripts/dse/run_full_flow_pilot.py --backend systemc --out runs/dse/generic_systemc_pilot
```

## Editing rule

Keep new work domain-neutral unless the task explicitly asks for a reference workload adapter.  Prefer generic workload-family, graph, mapping, and evidence vocabulary over application-specific names in core code.
