# QE-IC Layer-6 Synthetic Feedback Calibration

## Artifact Role

This artifact compares Layer-4 promotion decisions and Layer-5A L1 analytical estimates against synthetic high-fidelity replay labels. It calibrates the next-round search policy and records whether the campaign should continue under synthetic replay stopping conditions.

## Metrics

- Promotion precision: 0.4166666666666667.
- False promotion rate: 0.5.
- Wasted budget ratio: 0.5833333333333334.
- Useful candidate count: 5.
- Top-k useful count: 5.

## Stopping Decision

Decision basis: `synthetic_replay_stop_decision`. Decision: `stop`. Reasons: top_k_useful_count_target_reached.

## Claim Boundary

This artifact contains synthetic replay feedback calibration only. It is not measured hardware execution evidence and does not prove final performance.

No SystemC, gem5, Vivado, DC, QE, RTL, or HLS execution was run. The labels are synthetic replay labels only and are not measured hardware performance.
