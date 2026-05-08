# AGENTS Guide - Runtime API

## Purpose

Domain-neutral C ABI for SE/FS proxy programs. Provides stable offload command descriptors and runtime metrics before full application adapters are linked.

## Interface

- `command_descriptor.h` - Generic offload command descriptor with `offload_*` aliases
- `offload_runtime.h/.c` - Synchronous submit, ROI markers, counters, JSON report emission

## Compatibility

- `qebs_*` symbols remain for QE band-solver prototype
- New backend code should use `offload_*` names
- Keep QE-specific data in adapter code, not here

## Claim Boundary

Runtime output is host/control proxy evidence only. Does not claim:
- Workload equivalence
- Cycle-accurate RTL timing
- Board measurement
- ASIC evidence
- Final architecture recommendation

## Integration Points

- **With adapters/qe_runtime/**: QE-specific adapter layer
- **With gem5_integration/**: Used by proxy programs for co-simulation

## Next Steps

- For QE adapter: see `adapters/qe_runtime/README.md`
- For SystemC model: see `model/qe_band_solver_model/AGENTS.md`
