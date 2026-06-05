# QE-IC Target Viability v1

## Artifact Role

This Layer-3 artifact consumes the Layer-1 QE-IC workload suite, the Layer-2 QE-IC motif profile, and a target-platform config fixture. It emits deterministic target viability estimates for configured GPU, FPGA, and GPU+FPGA hybrid target types.

## Summary

Record count: 42.
Baseline: 14; viable: 0; maybe: 20; reject: 8.

- `fpga_only`: records=14, baseline=0, viable=0, maybe=9, reject=5.
- `gpu_fpga_hybrid`: records=14, baseline=0, viable=0, maybe=11, reject=3.
- `gpu_only`: records=14, baseline=14, viable=0, maybe=0, reject=0.

## Modeling Boundary

The target platform values in the fixture are model parameters, not measured platform claims. Transfer and risk values are heuristic viability estimates, not measured hardware performance. Hybrid transfer estimates use a conservative GPU-FPGA movement proxy rather than a measured implementation model.

## Claim Boundary

This artifact contains target viability estimates only. It does not contain architecture candidates, promotion decisions, SystemC/gem5/Vivado requests, hardware implementation results, or final performance claims.

Layer-3 does not generate concrete architectures, RTL, SystemC/gem5 requests, Vivado requests, promotion decisions, hardware implementation results, or final performance claims.
