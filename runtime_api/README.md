# Backend proxy runtime API

`runtime_api/` is the domain-neutral C boundary for proxy programs before a full workload profile/importer path is linked in.

- `command_descriptor.h` defines the offload command descriptor and MMIO/control vocabulary.
- `offload_runtime.h/.c` provide synchronous submit, ROI markers, MMIO/DMA/control counters, and JSON report emission.
- The GSIM descriptor structs in `command_descriptor.h` are the domain-neutral
  gem5 GenericAccel ABI.  The first 48 bytes remain compatible with existing
  descriptor/request/result/completion runs; optional pointer/size extension
  fields carry candidate identity, compile/runtime schedules, sidecar dispatch,
  and adapter payload JSON without adding QE-specific fields to the C ABI.

New code should use the `offload_*` aliases.  Older symbol names are compatibility shims and should not define new mainline semantics.
