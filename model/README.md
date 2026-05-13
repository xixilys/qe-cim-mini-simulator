# Model Directory

`model/` now contains the active generic simulator stack.

## Active model

- `model/generic_sim_backend/` — JSON-driven C++ timing backend used as the L3 SystemC-style simulator for DSE.

## Build

```bash
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j
```

## Run

```bash
model/generic_sim_backend/build/generic_sim \
  --request path/to/simulation_request.json \
  --result path/to/simulation_result.json
```

## Legacy material

Old application-specific models were moved from the active tree.  Do not add new mainline work there unless the user explicitly asks to restore a scoped reference.
