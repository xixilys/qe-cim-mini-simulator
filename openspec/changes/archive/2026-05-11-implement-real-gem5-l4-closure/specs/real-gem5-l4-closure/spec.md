## ADDED Requirements

### Requirement: Real gem5 L4 closure emits a machine-checkable proof
The system SHALL emit `gem5_l4_proof.json` for a real `gem5_systemc --gem5-real-l4` run only when the gem5-driven path exercises descriptor or request ingestion, SystemC backend submission, completion or result writeback, guest-visible success, and passed SystemC result status.

#### Scenario: Passing proof records every required check
- **WHEN** a real gem5+SystemC run completes descriptor/request ingestion, SystemC backend submission, completion/result writeback, guest-visible success, and a passed SystemC result
- **THEN** `gem5_l4_proof.json` records each required check as passed and sets the overall proof status to passed

#### Scenario: Incomplete proof remains untrusted
- **WHEN** any required L4 proof check is missing or failed
- **THEN** `gem5_l4_proof.json` records the failed or missing check and the sample remains ineligible for trusted L4 claims

### Requirement: Real L4 proof has bounded claim scope
The system SHALL treat a passing real L4 proof as evidence for gem5-to-SystemC transport, descriptor/request flow, completion flow, and timing-result replay only. It SHALL NOT imply QE FP64 physics correctness, board correctness, RTL correctness, or comparative best-architecture correctness.

#### Scenario: Passing L4 proof enables transport timing claim only
- **WHEN** `gem5_l4_proof.json` passes for a generic heterogeneous backend run
- **THEN** claim validation may mark descriptor/request transport and timing-result replay claims as trusted
- **AND** claim validation keeps physics, board, RTL, and comparative winner claims outside the L4 proof boundary unless separate evidence is present

### Requirement: Missing real L4 execution cannot synthesize trusted evidence
The system SHALL NOT generate synthetic `gem5_l4_proof.json`, `verdict.json`, or `simulation_result.json` artifacts that imply L4 completion when a real gem5 L4 run was not executed.

#### Scenario: Missing real L4 flag fails before evidence synthesis
- **WHEN** a user requests `backend=gem5_systemc` without the real L4 harness flag
- **THEN** the command fails explicitly before creating trusted gem5 evidence artifacts

### Requirement: Real L4 artifacts support audit replay
The system SHALL persist the raw logs, descriptor/request artifacts, completion artifacts, command line, and proof file needed to audit or replay a real gem5 L4 run.

#### Scenario: Proof links raw evidence files
- **WHEN** `gem5_l4_proof.json` is produced
- **THEN** it references the gem5 log, stdout/stderr, command descriptor, completion descriptor, simulation request, simulation result, and replay command or configuration used for the run
