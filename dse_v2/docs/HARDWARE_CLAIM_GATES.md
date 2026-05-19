# Hardware Claim Gates

`dse_v2.codesign.hardware_claim_gates` validates Step3/Step4 evidence records
before any accelerated-kernel FPGA or ASIC claim is allowed.

## Required chain

Every hardware claim must pass:

1. golden/kernel/numerical correctness;
2. HLS C-simulation or RTL simulation;
3. HLS C-synthesis or RTL synthesis;
4. the claim-specific physical branch:
   - FPGA: Vivado synthesis or implementation;
   - ASIC: Design Compiler synthesis, timing, and area, or one combined
     `dc_synth_timing_area` artifact.

DC-only evidence is a blocker for FPGA claims. Vivado-only evidence is a
blocker for ASIC claims. Tool-unavailable logs with command, environment, and
failure evidence are useful audit records, but they remain blockers and never
become pass evidence.

## Targeted checks

```bash
python3 -m pytest -q dse_v2/tests/test_hardware_claim_gates.py
python3 -m compileall dse_v2
```

This gate does not run DC, VCS, or Vivado itself and does not make timing, area,
PPA, FPGA, or ASIC implementation claims. Real tool transcripts must be
produced by the EDA flow before this validator can allow a matching claim.
