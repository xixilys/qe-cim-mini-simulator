# CLAUDE Guide

Use this repository as a generic accelerator DSE workspace with an active
DFT/QE full-SCF hardware DSE proof path.  Keep the reusable control plane
domain-neutral while allowing DFT/QE-specific facts, workload bundles,
candidate templates, and evidence reports inside scoped reference
workload/profile layers.

## Mainline scope

- DSE design-space exploration and evidence flow: `dse_v2/`
- Generic timing backend: `model/generic_sim_backend/`
- gem5 GenericAccel L4 path: `gem5_integration/src/dev/generic_accel/`, `gem5_integration/configs/generic_accel_l4_test.py`, `gem5_integration/test_programs/generic_accel/`
- Domain-neutral proxy ABI: `runtime_api/`
- Generic docs: `docs/architecture/generic_dse*`, `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md`
- Active DFT/QE proof-path manual: `docs/architecture/dft_scf_hardware_dse_design_manual.md`
- Scoped reference profiles/adapters: `dse_v2/reference_workloads/`

## Legacy material boundary

QE/DFT/Ozaki-specific historical material should not be recreated wholesale or moved into core code. Restore or recreate only scoped fixtures needed for the active DFT/QE proof path or explicit multi-workload validation, and keep claim boundaries clear.

## Useful commands

```bash
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j
python3 -m pytest -q dse_v2/tests
python3 dse_v2/scripts/dse/run_full_flow_pilot.py --backend systemc --out runs/dse/generic_systemc_pilot
```

## Editing rule

Keep new core work domain-neutral.  Put DFT/QE-specific semantics in reference workload/profile/adapters and docs, not in core IR, mapping, or reusable schemas.  Full-SCF hardware claims must include host-bound costs and pass the required correctness/SystemC/gem5/FPGA/IC-EDA gates; blocked, model-only, or unavailable-tool evidence is progress only.
