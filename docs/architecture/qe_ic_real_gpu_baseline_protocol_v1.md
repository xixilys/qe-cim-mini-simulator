# QE-IC Real GPU Baseline Protocol v1

## Required Baseline Evidence

A real GPU-only baseline requires:

- the same workload family, case, program, input deck hash, and precision used
  for candidate comparison;
- at least three repeated GPU-only QE runs;
- runtime mean, sample standard deviation, and 95 percent confidence interval;
- GPU model, driver, CUDA version, QE version, and platform precision;
- GPU utilization;
- memory-bandwidth utilization, host-device transfer time, and communication
  time when available;
- profile artifact hash;
- `measurements_are_real=true`;
- `evidence_status=measured`.

Unavailable metrics must be represented as unavailable or estimated in upstream
capture. They must not be silently treated as measured.

## Ingest Mode

`ingest_only` accepts externally produced JSON records. The campaign validates
that records are real measurements before they can enter the existing claim
gate. Invalid, fixture, or template-only records produce `evidence_missing`.

## Missing Inputs

If QE, GPU profiling, or input decks are unavailable, the campaign still emits a
valid report. The final answer must say which baseline evidence is missing and
must not infer GPU-vs-FPGA speedup.
