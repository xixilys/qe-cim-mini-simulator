# GenericAccel gem5 Device Model

This directory contains the workload-family neutral `GenericAccel` SimObject
used by the L4 evidence path.

**Status: in-gem5 microarchitecture model.**  The device reads a guest-visible
GSIM command descriptor, copies and parses the JSON request payload, builds a
micro-op schedule for descriptor decode, DMA transfers, compute operations, and
completion writeback, then writes a result JSON plus a guest-visible completion
descriptor.  L4 trust is still evidence-gated; a gem5 process exit is not enough.

## Architecture

```text
gem5 guest driver
    |
    | MMIO doorbell + guest workspace descriptor
    v
GenericAccel
    |-- descriptor_read
    |-- uarch_request_decode
    |-- DMA/compute/completion micro-op schedule
    |-- result JSON writeback
    |-- completion descriptor writeback
```

## Files

- `generic_accel.hh/cc` — C++ device model and microarchitecture schedule.
- `GenericAccel.py` — SimObject definition.
- `SConscript` — Build configuration.
- `generic_mmio_protocol.md` — MMIO register map.

## Mainline scope

GenericAccel is domain-neutral: command descriptors carry JSON request/result
addresses, and timing semantics come from `WorkloadPackage`, `ComputeGraph`,
mapping, architecture knobs, and backend request artifacts. Legacy
application-specific devices are not part of this active directory.

## Required evidence before trusted L4 claims

A run may claim trusted L4 software-visible microarchitecture evidence only when
the artifact set contains:

- `gem5.log` lines proving `descriptor_read`, `uarch_request_decode`,
  `microarchitecture_execute`, and `completion_writeback`;
- a GSIM command descriptor with verified request/result guest addresses;
- a result JSON produced by the GenericAccel microarchitecture path;
- a completion descriptor visible to guest software; and
- guest stdout showing success status plus completion descriptor status 0.

Without those artifacts, use the blocked verdict path in
`dse_v2.backends.gem5_systemc_adapter`; fixed-timing MMIO bring-up remains
diagnostic only.
