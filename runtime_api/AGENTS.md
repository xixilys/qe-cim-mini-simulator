# AGENTS Guide - runtime_api/

## Purpose

Domain-neutral C ABI for proxy offload programs and gem5 SE/FS experiments.

## Active interface

- `command_descriptor.h` — command descriptor and MMIO register vocabulary.
- `offload_runtime.h/.c` — synchronous submit, ROI markers, counters, JSON report emission.

## Rules

- Use `offload_*` names for exported ABI symbols and macros.
- Keep application-specific payload semantics outside this directory.
- Runtime output is proxy/control evidence only; it does not prove workload correctness, RTL timing, board measurement, or final architecture ranking.
