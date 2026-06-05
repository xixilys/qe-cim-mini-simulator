# QE-IC Closed-Loop DSE Campaign v1

## System Goal

This artifact bundle connects the QE-IC Layer-1 workload suite through Layer-6 synthetic feedback calibration. It asks whether a budgeted DSE loop can reduce false promotions and improve next-round candidate selection under a fixed synthetic replay budget.

## Result Summary

- Candidates: 29.
- Promoted by Layer-4: 12.
- L1 analytical result count: 12.
- Synthetic labels replayed: 14.
- Useful synthetic candidates: 5.
- False promotions: 6.
- Promotion precision: 0.4166666666666667.
- Wasted budget ratio: 0.5833333333333334.
- Synthetic stop decision: stop.

## Layer-6 Synthetic Feedback

Layer-6 synthetic feedback compares L1 estimates and Layer-4 promotion decisions with replay labels, then emits adaptive policy state and a next-round plan. This is not measured hardware performance.

## Claim Boundary

This artifact summarizes a QE-IC closed-loop DSE campaign through Layer-6 synthetic feedback calibration only. It does not contain SystemC/gem5/Vivado/DC/QE execution results, measured hardware performance, or final FPGA/GPU/GPU+FPGA superiority claims.

The bundle does not prove FPGA is faster than GPU, does not prove GPU+FPGA is faster than GPU, and does not include final PPA or hardware-proven candidate claims.
