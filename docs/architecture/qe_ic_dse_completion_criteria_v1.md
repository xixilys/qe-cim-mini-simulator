# QE-IC DSE Completion Criteria v1

## Campaign Completion Conditions

A synthetic closed-loop campaign is complete when Layer-1 through Layer-5A
artifacts validate, Layer-6 synthetic feedback validates, the system result
recomputes summaries from underlying artifacts, candidate trajectories link
Layer-4/5A/6 state, and stopping conditions are reported as
`synthetic_replay_stop_decision`.

Deliverable completion for hardware claims is stricter: real full-SCF workloads,
tool-specific correctness, synthesis, implementation, end-to-end timing and
energy accounting, and replayable provenance must be present for every claimed
accelerated path.

## Success Metrics

Synthetic campaign success is measured by promotion precision, false promotion
rate, wasted budget ratio, useful candidate count, top-k useful count, ranking
mismatch count, calibration error, and whether the next-round plan prioritizes
better candidates under the configured budget.

## Failure Metrics

Failure metrics include high false promotion rate, high wasted budget ratio,
unknown candidate references, missing L1 or feedback state for promoted
candidates, inconsistent recomputed summaries, invalid stopping decisions, and
any forbidden measured or hardware-proven claim.

## Future Baseline Comparisons

Future real experiments must compare against a representative GPU baseline and
include full-SCF host/device accounting. CPU I/O, SCF control, convergence
checks, diagonalization, mixing, synchronization, and transfers must remain in
end-to-end timing and energy accounting.

## Minimum Evidence Before Hardware Usefulness Claims

Before claiming hardware usefulness, each accelerated kernel must pass golden
correctness, HLS C-sim or RTL simulation, HLS C-synth or RTL synthesis, and the
target-specific implementation gate. FPGA claims require Vivado synthesis and
implementation evidence. ASIC claims require DC synthesis, timing, and area
evidence. Synthetic replay, L1 estimates, and planning artifacts are not enough.
