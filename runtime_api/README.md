# Backend proxy runtime API

`runtime_api/` is the domain-neutral C boundary used by SE/FS proxy programs before a full application adapter is linked in.  The ABI is intentionally small:

- `command_descriptor.h` defines a generic offload command descriptor plus stable aliases (`offload_*`) for new users.
- `offload_runtime.h/.c` provide synchronous submit, ROI markers, MMIO/DMA/control counters, and JSON report emission.
- Existing `qebs_*` symbols remain as compatibility aliases for the current QE band-solver prototype; new backend code should prefer the `offload_*` names and keep QE-specific data in adapter code.

Claim boundary: runtime output is host/control proxy evidence only.  It does not claim workload equivalence, cycle-accurate RTL timing, board measurement, ASIC evidence, or final architecture recommendation.
