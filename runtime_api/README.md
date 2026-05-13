# Backend proxy runtime API

`runtime_api/` is the domain-neutral C boundary for proxy programs before a full workload profile/importer path is linked in.

- `command_descriptor.h` defines the offload command descriptor and MMIO/control vocabulary.
- `offload_runtime.h/.c` provide synchronous submit, ROI markers, MMIO/DMA/control counters, and JSON report emission.

New code should use the `offload_*` aliases.  Older symbol names are compatibility shims and should not define new mainline semantics.
