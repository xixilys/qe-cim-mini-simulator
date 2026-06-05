# QE-IC Candidate Plan v1

## Layer-4 Role

Layer-4 is the first QE-IC layer that turns workload, motif, and target-viability analysis into DSE decisions. It generates candidate design specifications, promotion decisions, and planned next-fidelity evaluation requests for later runners.

## Candidate Generation Boundary

Candidates are generated from Layer-3 viability records and a template registry. GPU-only records produce baseline reference candidates. Reject records do not produce accelerator candidates. Maybe and viable records can produce FPGA-only or GPU+FPGA hybrid candidates when the campaign allows the target type and template family.

## Promotion Policy Boundary

The default policy is deterministic and modular. It extracts features from candidates and source viability records, scores them with explicit weights, applies budget and diversity filters, and assigns reason codes. The policy is a planning rule, not a final performance adjudicator.

## Budget Constraints

L1 cost-model requests used: 12 of 12. SystemC, gem5, Vivado, DC, and real-QE request budgets are zero in this Layer-4 artifact.

## Diversity Logic

Target-type diversity required: True. Motif diversity required: True. Promoted target types: fpga_only, gpu_fpga_hybrid. Promoted motifs: cross_run_reuse, fft_transpose, hpsi, localized_state_analysis, perturbation_rhs, reduction_collective, response_accumulation, workflow_parameter_sweep.

## Summary

Candidates: 29; baseline=14; promote=12; hold=3; reject=0; evaluation requests=12.

- `fpga_only`: candidates=7, baseline=0, promote=7, hold=0, reject=0.
- `gpu_fpga_hybrid`: candidates=8, baseline=0, promote=5, hold=3, reject=0.
- `gpu_only`: candidates=14, baseline=14, promote=0, hold=0, reject=0.

## Offline Replay Validation Meaning

Synthetic replay labels can be used to check whether a promotion policy avoids obvious false promotions and reports wasted-budget and precision metrics. Those labels are controlled test fixtures only. They are not real QE, FPGA, GPU, or hardware evidence.

## Claim Boundary

This artifact contains candidate specifications and promotion plans only. It does not contain executed SystemC/gem5/Vivado/QE results, hardware implementation results, or final performance claims.

No execution results are included. No SystemC, gem5, Vivado, DC, real QE, RTL, or HLS tool was run by Layer-4. No final performance, PPA, FPGA, GPU, or GPU+FPGA superiority claim is made by this artifact.
