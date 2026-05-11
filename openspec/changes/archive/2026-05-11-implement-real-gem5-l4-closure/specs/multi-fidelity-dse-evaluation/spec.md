## ADDED Requirements

### Requirement: Gem5 SystemC samples require passing L4 proof for trusted eligibility
The multi-fidelity evaluator SHALL keep `backend="gem5_systemc"` samples untrusted unless the sample includes a passing `gem5_l4_proof.json` artifact. Passing proof MAY make the sample eligible for trusted L4 transport/timing replay claims subject to the TrustGate.

#### Scenario: Passing proof promotes gem5 sample to trusted L4 eligibility
- **WHEN** a promoted `gem5_systemc` sample includes a passing `gem5_l4_proof.json`
- **THEN** `mapping_simulation_samples.json` records the sample with `trusted_final_eligible=true` for bounded L4 transport/timing replay
- **AND** the sample evidence ids include `gem5_l4_proof.json`

#### Scenario: Missing proof keeps gem5 sample diagnostic
- **WHEN** a promoted `gem5_systemc` sample lacks a passing `gem5_l4_proof.json`
- **THEN** `mapping_simulation_samples.json` records `trusted_final_eligible=false` with a missing or failed proof blocker

### Requirement: L3 SystemC trust remains independent of L4 availability
The multi-fidelity evaluator SHALL continue to allow trusted standalone SystemC L3 samples when their full-flow SystemC evidence passes, even if real gem5 L4 execution is unavailable or blocked.

#### Scenario: L3 full-flow remains trusted when L4 is not run
- **WHEN** a standalone SystemC full-flow sample passes its evidence checks and gem5+SystemC is not run
- **THEN** the sample may remain trusted L3 evidence and the run records L4 as not run rather than failed
