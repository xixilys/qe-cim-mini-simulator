# QE-IC Closed-Loop DSE System v1

## Why Layer-1 Through Layer-5A Is Not Enough

Layer-1 through Layer-5A define the workload scope, motif profile, target
viability, candidate plan, and L1 analytical estimates. That is enough to build
a deterministic search front end, but it is not enough to assess whether the
search policy is learning from mistakes. A policy can promote candidates with
plausible L1 estimates that later fail because of resource pressure, transfer
overhead, or poor ranking.

Closed-loop DSE requires feedback. Layer-6 compares low-fidelity predictions
and promotion decisions against synthetic high-fidelity replay labels, then
updates risk thresholds, template/motif/target risk adjustments, acquisition
priorities, next-round suggestions, and stopping-condition state.

## Layer Roles

- Layer-1 defines the QE-IC workload suite and excluded workflows.
- Layer-2 maps workload profiles to reusable motifs and GPU-baseline context.
- Layer-3 estimates GPU, FPGA, and GPU+FPGA target viability.
- Layer-4 generates candidate plans and budgeted promotion decisions.
- Layer-5A evaluates promoted candidates with deterministic L1 analytical cost
  models.
- Layer-6 calibrates the search policy using synthetic replay labels and emits
  adaptive next-round state.

## Candidate Validity Levels

- `C0_contract_valid`: the candidate is structurally valid in Layer-4.
- `C1_l1_plausible`: the candidate has a Layer-5A analytical estimate.
- `C2_synthetic_feedback_useful`: synthetic replay labels mark the candidate as
  useful or previously under-promoted.
- `C3_synthetic_feedback_false_promotion`: synthetic replay labels mark the
  candidate as a false promotion, resource-invalid, or overhead-invalid.
- `C4_high_fidelity_required`: the candidate remains unresolved and needs a
  future real high-fidelity gate.
- `C5_hardware_proven`: forbidden in this system. Validation fails if it
  appears.

## False Promotion Meaning

A false promotion is a candidate selected by Layer-4 for the next fidelity that
synthetic replay later labels as not useful. The current label classes include
`false_promotion`, `resource_invalid`, and `overhead_invalid`. These are
synthetic replay outcomes only; they are not measured SystemC, gem5, Vivado,
DC, QE, RTL, or HLS evidence.

## Synthetic Replay Use

Synthetic replay gives the control plane a deterministic feedback signal for
testing closed-loop behavior before real expensive tool execution exists. It is
used to compute promotion precision, false promotion rate, wasted budget ratio,
ranking mismatch count, top-k useful count, calibration error, candidate label
coverage, adaptive policy updates, and synthetic stopping decisions.

## Final System Output

The final campaign artifact summarizes a replayable QE-IC campaign through
Layer-6. It links source artifacts, layer validation status, system summary
counts, candidate trajectories, feedback metrics, adaptive policy state, and the
next-round plan.

## Claims It Cannot Make Yet

The system cannot claim FPGA is faster than GPU, GPU+FPGA is faster than GPU,
L1 estimates are measured performance, any candidate is hardware-proven, or any
final physical PPA result exists. The output is a closed-loop DSE control-plane
artifact, not final hardware evidence.

## Future Real Integration

Future SystemC, gem5, Vivado, DC, RTL/HLS, and real QE integration would replace
or supplement synthetic labels with tool-specific evidence. Those gates would
add measured or implementation-backed correctness, timing, resource, area,
power, and end-to-end accounting fields. Final hardware usefulness claims still
require claim-specific evidence gates and cannot be inferred from Layer-6
synthetic replay alone.
