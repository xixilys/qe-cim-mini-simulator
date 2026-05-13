# AGENTS Guide - model/

## Scope

Active model work is in `model/generic_sim_backend/`.

## Build/test

```bash
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j
ctest --test-dir model/generic_sim_backend/build --output-on-failure
```

## Rules

- Keep simulator requests/results JSON-visible and domain-neutral.
- Use C++17.
- Prefer explicit loops and small helper functions.
- If a workload requires domain-specific semantics, pass them through adapter metadata rather than hardcoding them in the simulator core.
