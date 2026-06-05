# QE-IC Measurement Protocol v1

## Goal

This protocol describes the minimum information needed to replace fixture
evidence with real GPU baseline and candidate high-fidelity evidence for QE-IC
opportunity analysis.

## GPU Baseline Measurements

A GPU-only baseline record must include:

- Program and workload family.
- Stable case identifier and input deck hash.
- QE, CUDA, driver, CPU, GPU, memory, and precision metadata.
- At least the configured minimum repeated runtime runs.
- Mean runtime, standard deviation, and 95 percent confidence interval.
- GPU utilization and GPU memory-bandwidth utilization.
- Host-device transfer and communication timing.
- Profile artifact hash.

`measurements_are_real=true` and `evidence_status=measured` are required before
the baseline can support a claim.

## Candidate Evidence

Candidate evidence may be `systemc_timing`, `gem5_systemc`,
`vivado_resource_timing`, `trace_replay`, or `real_qe_run`. `l1_estimate_only`
can be ingested for diagnostics but cannot support a GPU-vs-FPGA opportunity
claim.

Candidate records must include workflow runtime, kernel runtime, transfer
overhead, workflow overhead, confidence intervals, repeated runs, architecture
summary, resource feasibility, timing feasibility, utilization summaries, and
an evidence artifact hash. High-fidelity estimates must include explicit tool
provenance.

## Workflow Accounting

The measured or high-fidelity candidate runtime must represent the workflow
claim being made. If the candidate only accelerates a kernel, the end-to-end
workflow record must still include retained CPU stages, I/O, SCF control,
convergence checks, diagonalization, mixing, synchronization, and transfer
costs. Kernel-only timing is insufficient for a workflow-level speedup claim.

## Fixture Replacement

To replace fixture evidence, point the opportunity config to new
`gpu_baseline_measurements` and `candidate_high_fidelity_results` JSON files.
The report will remain inconclusive until those files pass validation and the
claim gates pass.
