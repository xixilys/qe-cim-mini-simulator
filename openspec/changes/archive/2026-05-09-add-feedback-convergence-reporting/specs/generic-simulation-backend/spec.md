## ADDED Requirements

### Requirement: gem5 plus SystemC trust requires an explicit L4 proof artifact
A gem5+SystemC sample SHALL enter trusted L4 evidence only when `gem5_l4_proof.json` exists and passes. The proof SHALL check descriptor or request ingestion, SystemC backend submission, completion/result writeback, guest-visible success, and passed SystemC result status.

#### Scenario: Passing L4 proof enables trusted gem5 sample
- **WHEN** a gem5+SystemC run records descriptor/request ingestion, SystemC submission, completion writeback, guest-visible success, and a passed SystemC result
- **THEN** `gem5_l4_proof.json` passes and the sample may be eligible for trusted L4 transport/timing claims

#### Scenario: Missing L4 proof blocks L4 trust
- **WHEN** a gem5+SystemC run lacks descriptor ingestion, backend submission, result writeback, guest-visible completion, or passed result evidence
- **THEN** the run is labeled blocked/prototype for L4 and does not enter trusted final ranking as gem5+SystemC evidence

### Requirement: L4 proof states its numerical and physical claim boundary
The backend evidence SHALL state that L4 proof covers gem5 descriptor/request/SystemC/completion transport plus generic timing-result replay. It SHALL NOT claim QE FP64 residual, density, eigenvector, physical SCF convergence, or board/ASIC correctness unless separate domain evidence exists.

#### Scenario: L4 report avoids QE physics overclaim
- **WHEN** a final report cites a passing `gem5_l4_proof.json`
- **THEN** the report states the transport/timing claim boundary and keeps QE FP64 physics correctness outside the trusted claim

#### Scenario: Numerical validation remains separately cited
- **WHEN** a gem5+SystemC sample is trusted for L4 transport/timing
- **THEN** the report also cites `numerical_validation.json` for generic timing numeric checks and labels the validation scope explicitly

### Requirement: Backend sample records preserve proof status and unavailable reasons
Simulation sample records SHALL include backend-specific proof status. For gem5+SystemC, the sample SHALL reference `gem5_l4_proof.json`; for standalone SystemC, the sample SHALL state that L4 proof is not applicable rather than treating it as a missing failure.

#### Scenario: Standalone SystemC sample is not penalized for missing L4 proof
- **WHEN** a standalone SystemC sample passes phase coverage and numerical validation
- **THEN** it may be trusted as L3 SystemC evidence while recording that L4 proof is not applicable

#### Scenario: gem5 proof path is visible in sample evidence
- **WHEN** a gem5+SystemC sample is recorded in `mapping_simulation_samples.json`
- **THEN** its evidence ids include `gem5_l4_proof.json` or its missing-proof reason is listed in the sample record
