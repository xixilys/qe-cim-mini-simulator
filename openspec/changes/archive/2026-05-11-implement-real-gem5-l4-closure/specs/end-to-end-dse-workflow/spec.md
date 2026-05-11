## ADDED Requirements

### Requirement: End-to-end gem5 L4 runs export proof and verdict artifacts
The end-to-end DSE workflow SHALL export `gem5_l4_proof.json`, raw gem5/SystemC logs, descriptor/request artifacts, completion artifacts, `verdict.json`, `mapping_simulation_samples.json`, and `claim_validation.json` for every real `gem5_systemc --gem5-real-l4` run that reaches the evidence stage.

#### Scenario: Real L4 full-flow exports audit artifacts
- **WHEN** a real `gem5_systemc --gem5-real-l4` full-flow run completes
- **THEN** the run directory contains the L4 proof, raw logs, descriptor/request evidence, completion evidence, simulation result, verdict, sample record, and claim validation artifacts needed for audit

### Requirement: End-to-end reports propagate L4 blockers honestly
The end-to-end DSE workflow SHALL propagate missing, failed, or incomplete L4 proof status into verdicts, sample records, claim validation, and final reports instead of silently omitting the attempted L4 path.

#### Scenario: Failed L4 proof appears in final evidence
- **WHEN** a real `gem5_systemc --gem5-real-l4` run fails a required L4 proof check
- **THEN** the final evidence records the failed check, marks the sample untrusted for L4, and reports the blocker without using that sample for trusted gem5 claims

#### Scenario: Passing L4 proof is linked from trusted claim
- **WHEN** a final report makes a trusted gem5 transport/timing replay claim
- **THEN** the claim links to the passing `gem5_l4_proof.json` and the associated SystemC result artifacts
