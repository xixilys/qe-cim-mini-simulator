# QE-IC FPGA/Hybrid Implementation Quality Gate v1

## Purpose

Poor FPGA/hybrid performance does not automatically prove that an architecture
or motif has no opportunity. The quality gate separates current implementation
limitations from fundamental lack of opportunity.

## Implementation-Limited Signals

The campaign classifies a losing candidate as `implementation_limited` when
evidence indicates:

- low pipeline utilization;
- insufficient memory bandwidth;
- poor transfer overlap;
- high synchronization overhead;
- low fmax;
- resource pressure;
- poor buffering or batching;
- immature implementation;
- functional proxy only;
- uncalibrated SystemC/proxy evidence.

If actual speedup is at or below 1.0 but the idealized upper bound is above
1.0, the classification is `implementation_limited`.

## Fundamental No-Opportunity Rule

`fundamental_no_opportunity` is only allowed when:

- a real GPU baseline exists;
- workflow-level candidate evidence exists;
- implementation quality passes;
- resource and timing are feasible, or infeasibility is architecture-intrinsic;
- the idealized upper bound is at or below 1.0;
- no claim gate passes;
- missing evidence is not the reason.

Unknown implementation quality must not be used to conclude fundamental lack of
opportunity.
