# QE-IC Real Baseline Opportunity Analysis v1

## Purpose

This layer answers one narrow research question: in a real GPU baseline setting,
do FPGA-only or GPU+FPGA hybrid candidates have a claim-gated opportunity for a
QE-IC workload family and motif?

It sits above the existing Layer-1 through Layer-6 DSE artifacts. It does not
replace search, candidate generation, L1 screening, or synthetic feedback. It
ingests those artifacts for traceability, then requires explicit GPU baseline
measurements and candidate high-fidelity results before allowing a GPU-vs-FPGA
or GPU-vs-hybrid opportunity claim.

## Inputs

The opportunity config references:

- Layer-1 workload suite.
- Layer-2 motif profile.
- Layer-3 target viability.
- Layer-4 candidate plan.
- Layer-5A L1 cost-model results.
- Layer-6 closed-loop DSE results.
- GPU-only baseline measurement records.
- FPGA-only or GPU+FPGA candidate high-fidelity result records.

The first six inputs establish DSE provenance and workload/candidate identity.
The last two inputs are the only performance evidence used for claim gating.

## Report Semantics

Each opportunity record matches a candidate result to a GPU baseline by
`workload_family_id`. The report computes:

```text
speedup_vs_gpu_mean =
  gpu_baseline.runtime_seconds_mean / candidate.workflow_runtime_seconds_mean

speedup_vs_gpu_conservative_ci =
  gpu_baseline.confidence_interval_95.low / candidate.confidence_interval_95.high
```

If workflow runtime is missing, the candidate is treated as kernel-only evidence
and cannot make a workflow-level claim. Host control, transfer overhead,
synchronization, and workflow overhead remain visible in the record.

## Verdicts

Record verdicts are:

- `evidence_missing`
- `fixture_only_inconclusive`
- `gpu_dominant_no_fpga_opportunity`
- `fpga_opportunity_found`
- `hybrid_opportunity_found`
- `fpga_or_hybrid_inconclusive`
- `candidate_invalid_resource`
- `candidate_invalid_transfer_overhead`
- `candidate_invalid_workflow_overhead`

System verdicts summarize the records without promoting fixture evidence into a
real claim.

## Claim Boundary

L1 analytical estimates and synthetic feedback labels remain search and
calibration evidence. They can explain why a candidate was promoted or why more
evidence is needed, but they cannot prove that FPGA or GPU+FPGA is stronger or
weaker than GPU-only. A final opportunity claim requires a measured GPU baseline
and candidate measured or explicitly high-fidelity evidence that passes the
claim gates.
