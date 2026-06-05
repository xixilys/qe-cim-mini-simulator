# QE-IC L1 Cost Model v1

## Layer-5A Role

Layer-5A consumes the Layer-4 QE-IC candidate plan and executes only planned `L1_cost_model` evaluation requests. It produces deterministic analytical estimates for promoted non-baseline FPGA-only and GPU+FPGA hybrid candidates.

## Analytical Estimate Meaning

An L1 cost-model result is a lightweight model estimate built from the candidate spec, template parameters, motif profile, target viability record, and promotion evidence. It estimates runtime, transfer, memory, communication, resource pressure, confidence, and risk. These estimates are not measured performance.

## Inputs Consumed

- Layer-1 suite artifact: `qe_ic_workload_suite.json`.
- Layer-2 motif profile artifact: `qe_ic_motif_profile.json`.
- Layer-3 target viability artifact: `qe_ic_target_viability.json`.
- Layer-4 candidate plan artifact: `qe_ic_candidate_plan.json`.
- Model config: `qe_ic_l1_cost_model_fixture_config`.

## What Was Executed

Layer-5A evaluated 12 planned L1 cost-model requests. Completed estimates: 12; failed estimates: 0. Baseline candidates are carried only as reference metadata and do not receive accelerator L1 result records.

- `fpga_only`: requests=7, completed=7, failed=0.
- `gpu_fpga_hybrid`: requests=5, completed=5, failed=0.

## Next-Fidelity Suggestions

Suggestions are advisory `next_fidelity_suggestion` values for later request builders. They are not final promotion decisions and do not adjudicate FPGA, GPU, or hybrid superiority.

- `hold_for_more_profile`: 5.
- `promote_to_systemc_request`: 3.
- `promote_to_vivado_resource_request`: 1.
- `reject_before_high_fidelity`: 3.

## Model Boundary

The model is deterministic and local. It does not use randomness, network calls, hidden measurements, or external hardware-tool outputs. It does not run SystemC, gem5, Vivado, DC, real QE, HLS, RTL simulation, or any other high-fidelity execution path.

## Calibration Status

Calibration status: `fixture_prior`. Calibration source: `not_measured_hardware`. Future high-fidelity calibration required: True.

## Claim Boundary

This artifact contains deterministic L1 analytical cost-model estimates only. It does not contain SystemC/gem5/Vivado/DC/QE execution results, hardware implementation results, or final performance claims.

No SystemC/gem5/Vivado/DC/QE execution results are included. No HLS, RTL, FPGA, ASIC, or real-QE tool result is included. No final performance, PPA, FPGA, GPU, or GPU+FPGA superiority claim is made by this artifact.
