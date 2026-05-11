## ADDED Requirements

### Requirement: TrustGate validates L4 proof fields before gem5 eligibility
The TrustGate SHALL inspect `gem5_l4_proof.json` for explicit pass/fail fields covering descriptor/request ingestion, SystemC backend submission, completion/result writeback, guest-visible success, and SystemC result status before accepting any `gem5_systemc` sample as trusted L4 evidence.

#### Scenario: All proof fields pass
- **WHEN** a `gem5_systemc` sample has a `gem5_l4_proof.json` where every required L4 proof field passes
- **THEN** the TrustGate may mark the sample trusted for bounded L4 transport/timing replay claims

#### Scenario: Required proof field fails
- **WHEN** a required L4 proof field is missing or false
- **THEN** the TrustGate rejects the sample with a structured L4 proof rejection reason

### Requirement: TrustGate rejects synthetic or diagnostic gem5 evidence
The TrustGate SHALL reject synthetic, smoke-only, standalone compatibility-only, or diagnostic gem5 evidence for trusted L4 claims even when the underlying command exits successfully.

#### Scenario: Diagnostic gem5 evidence is blocked
- **WHEN** a `gem5_systemc` candidate cites smoke output, standalone TLM compatibility output, or diagnostic replay without a passing real L4 proof
- **THEN** the TrustGate labels the sample `l4_untrusted` and blocks trusted gem5-specific timing or transport claims
