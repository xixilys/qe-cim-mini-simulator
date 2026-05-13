# DSE v2

Generic multi-fidelity design-space exploration for heterogeneous accelerator systems.

## Fidelity ladder

- L1: analytical/roofline-style model
- L2: Python TLM model
- L3: generic simulator backend (`model/generic_sim_backend/build/generic_sim`)
- L4: gem5 GenericAccel descriptor/request/microarchitecture/completion evidence

## Run

```bash
python3 -m pytest -q dse_v2/tests
python3 dse_v2/scripts/dse/run_full_flow_pilot.py --backend systemc --out runs/dse/generic_systemc_pilot
```

## Scope rule

`reference_workloads/` may contain optional adapter examples.  Core IR, mapping, schemas, and backend paths must not depend on any one application domain.
