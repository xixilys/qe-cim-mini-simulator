# QE-IC Claim Gate For GPU/FPGA Comparison v1

## Gate Inputs

The claim gate receives one GPU-only baseline record, one FPGA-only or
GPU+FPGA candidate result, and the opportunity config thresholds. The baseline
must be measured. The candidate result must be measured or a high-fidelity
estimate with explicit tool provenance.

## Required Gates

A candidate can be marked `fpga_opportunity_found` or
`hybrid_opportunity_found` only when all configured gates pass:

- Matching GPU-only baseline exists.
- GPU baseline payload has `measurements_are_real=true`.
- Baseline record has `evidence_status=measured`.
- Candidate payload has `results_are_real=true`.
- Candidate evidence is not `fixture_example`.
- Candidate evidence is not `l1_estimate_only`.
- Candidate has workflow-level runtime unless the config explicitly allows
  kernel-only claims.
- Repeated run count meets `minimum_repeated_runs`.
- Mean speedup is at least `minimum_speedup_for_strong_claim`.
- Conservative CI speedup is above 1.0 when required.
- Resource feasibility is true when required.
- Timing feasibility is true when required.
- High-fidelity estimates include explicit tool provenance.

## Failure Reasons

The gate records blocker and failure codes such as:

- `gpu_baseline_missing`
- `fixture_only_evidence`
- `l1_only_insufficient`
- `kernel_only_insufficient`
- `confidence_interval_crosses_one`
- `transfer_overhead_dominates`
- `workflow_overhead_dominates`
- `resource_infeasible`
- `timing_infeasible`
- `gpu_utilization_high`
- `no_speedup_vs_gpu`
- `speedup_claim_gate_passed`

These reason codes are evidence accounting. They do not by themselves establish
that GPU or FPGA is superior; the full gate state and source evidence determine
whether the claim is allowed.

## Validation

Validation recomputes speedups, conservative CI speedup, blockers, failure
reasons, verdict, claim strength, and the system conclusion from raw claim-gate
inputs embedded in the report. Validation fails if a strong claim is made from
fixture evidence, L1-only evidence, missing baseline evidence, inconsistent
speedup fields, or an opportunity verdict with `claim_allowed=false`.
