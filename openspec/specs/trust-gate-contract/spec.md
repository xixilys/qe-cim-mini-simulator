# trust-gate-contract Specification

## Purpose
Define the unified trust gate contract that governs when a DSE sample, candidate, or claim may enter trusted final ranking, trusted comparative analysis, or trusted winner selection. The trust gate SHALL be the single authority for evidence eligibility across all DSE entry points including orchestrator, multi-fidelity evaluator, Step3 workflow, and final report generation.
## Requirements
### Requirement: TrustGate is the single authority for evidence eligibility
The system SHALL enforce that every trusted claim, trusted ranking entry, trusted Pareto member, and trusted winner selection passes through a unified TrustGate. No evaluator, orchestrator, report generator, or CLI entry point SHALL bypass the TrustGate or implement its own eligibility rules.

#### Scenario: Orchestrator routes all candidates through TrustGate
- **WHEN** `DSEOrchestrator.get_best_design()` or `DSEOrchestrator.get_pareto_frontier()` is invoked
- **THEN** the result contains only candidates that have passed the TrustGate; candidates without trusted high-fidelity evidence are excluded from the returned set

#### Scenario: Multi-fidelity evaluator blocks L1/L2 from final ranking
- **WHEN** `MultiFidelityEvaluator` promotes candidates from L1/L2 to L3/L4
- **THEN** L1/L2-only candidates remain in `trusted_final_eligible=false` state and cannot enter trusted ranking regardless of their screening score

#### Scenario: Step3 workflow blocks before simulation
- **WHEN** `run_step3_simulation_evidence_workflow()` receives a Step2 handoff
- **THEN** the TrustGate validates promotion decision, artifact completeness, claim boundary, and graph lowering status before launching the simulator

#### Scenario: Final report rejects untrusted claims
- **WHEN** `final_report.generate()` processes candidates
- **THEN** the TrustGate re-validates every candidate cited in trusted claims; any candidate that fails re-validation is downgraded to predicted-only or blocked

### Requirement: TrustGate defines mandatory evidence criteria
The TrustGate SHALL enforce the following mandatory criteria for trusted eligibility. ALL criteria MUST be satisfied; partial satisfaction SHALL result in blocked or untrusted status.

#### Scenario: High-fidelity evidence is mandatory
- **WHEN** a candidate is evaluated for trusted status
- **THEN** the candidate MUST have completed L3 (standalone SystemC) or L4 (gem5+SystemC) simulation with passing result status

#### Scenario: L1/L2 evidence is insufficient for trusted ranking
- **WHEN** a candidate has only L1 analytical or L2 TLM evaluation results
- **THEN** the TrustGate rejects the candidate for trusted ranking and labels it `predicted_only`

#### Scenario: Smoke or diagnostic evidence is insufficient
- **WHEN** a candidate has only smoke, bring-up, diagnostic, fixed-timing, or reduced-workload evidence
- **THEN** the TrustGate rejects the candidate for trusted ranking and labels it `diagnostic_only`

#### Scenario: Complete artifact set is mandatory
- **WHEN** a candidate claims trusted status
- **THEN** the TrustGate verifies that all required artifacts exist: `simulation_request.json`, `simulation_result.json`, `verdict.json`, and phase-coverage evidence

#### Scenario: Valid schema version is mandatory
- **WHEN** a candidate's evidence artifacts are inspected
- **THEN** the TrustGate validates that artifact schema versions are supported; unknown or incompatible schema versions result in blocked status

### Requirement: TrustGate distinguishes feasibility from comparative ranking
The TrustGate SHALL maintain separate eligibility categories for single-sample feasibility claims versus multi-sample comparative ranking claims.

#### Scenario: Single trusted sample may claim feasibility only
- **WHEN** exactly one candidate has trusted high-fidelity evidence
- **THEN** the TrustGate permits `trusted_feasibility=true` but sets `trusted_comparative_ranking=false` and prevents best-architecture or Pareto claims

#### Scenario: Comparative ranking requires multiple trusted samples
- **WHEN** a report claims mapping comparison, architecture comparison, or Pareto frontier
- **THEN** the TrustGate requires at least two trusted high-fidelity samples with comparable configurations

#### Scenario: Winner selection requires convergence evidence
- **WHEN** a report selects a best architecture or best mapping
- **THEN** the TrustGate requires either multiple trusted samples showing dominance or explicit convergence artifacts (`convergence_status.json`) supporting the selection

### Requirement: TrustGate enforces L4-specific proof requirements
For gem5+SystemC backend claims, the TrustGate SHALL enforce additional L4 proof requirements beyond L3 SystemC requirements.

#### Scenario: L4 claims require gem5_l4_proof.json
- **WHEN** a candidate uses `backend="gem5_systemc"` and claims trusted status
- **THEN** the TrustGate requires a passing `gem5_l4_proof.json` artifact; absence or failure blocks L4 trust

#### Scenario: L4 proof validates full-system path
- **WHEN** `gem5_l4_proof.json` is inspected
- **THEN** the TrustGate verifies that the proof covers descriptor/request ingestion, SystemC backend submission, completion/result writeback, and guest-visible success

#### Scenario: Missing L4 proof blocks gem5 claims
- **WHEN** a gem5+SystemC run lacks `gem5_l4_proof.json`
- **THEN** the TrustGate labels the sample `l4_untrusted` and does not permit gem5-specific timing or transport claims

### Requirement: TrustGate produces structured rejection reasons
When the TrustGate rejects a candidate, it SHALL produce structured rejection reasons with reason codes, severity, and remediation guidance.

#### Scenario: Rejection includes reason code
- **WHEN** the TrustGate blocks a candidate
- **THEN** the rejection includes a machine-readable `reason_id` (e.g., `l1_only_evidence`, `smoke_boundary`, `missing_l4_proof`, `incomplete_artifacts`, `schema_version_mismatch`)

#### Scenario: Rejection includes severity
- **WHEN** the TrustGate evaluates a candidate
- **THEN** the rejection includes `severity` (`fatal`, `error`, `warning`) indicating whether the issue is permanent, fixable, or informational

#### Scenario: Rejection includes remediation
- **WHEN** the TrustGate blocks a candidate with `severity=error`
- **THEN** the rejection includes `remediation` guidance describing what evidence or artifact is needed to achieve trusted status

### Requirement: TrustGate is idempotent and auditable
The TrustGate SHALL produce deterministic results for the same inputs and SHALL log all trust decisions for audit.

#### Scenario: Same inputs produce same trust decision
- **WHEN** the TrustGate is invoked twice with identical candidate evidence
- **THEN** both invocations produce identical trust decisions and identical rejection reasons

#### Scenario: Trust decisions are logged
- **WHEN** the TrustGate evaluates a candidate
- **THEN** the decision is recorded in `trust_gate_log.json` with timestamp, candidate id, decision, criteria checked, and criteria results

#### Scenario: Trust log supports audit replay
- **WHEN** an auditor reviews a DSE run
- **THEN** the trust gate log provides sufficient information to replay the trust decision without re-running the simulator

### Requirement: TrustGate integrates with claim validation
The TrustGate SHALL integrate with the claim validation system to ensure that every trusted claim has passed the trust gate.

#### Scenario: Claim validation checks trust status
- **WHEN** `claim_validation.json` is generated
- **THEN** every trusted claim includes a `trust_gate_passed` field; claims without this field or with `trust_gate_passed=false` fail validation

#### Scenario: Untrusted claims are labeled
- **WHEN** a claim references a candidate that failed the TrustGate
- **THEN** the claim is labeled `untrusted` and the validation report includes the trust gate rejection reason

### Requirement: TrustGate log writes are atomic and concurrency-safe
The TrustGate SHALL ensure that trust decision logs are written atomically and are safe under concurrent evaluation. Concurrent TrustGate evaluations SHALL NOT corrupt the trust log or produce inconsistent decisions.

#### Scenario: Concurrent trust evaluations append safely
- **WHEN** multiple candidates are evaluated by the TrustGate concurrently
- **THEN** each decision is appended atomically to `trust_gate_log.json` and no log entries are lost or interleaved

#### Scenario: Trust log supports concurrent read
- **WHEN** an auditor reads `trust_gate_log.json` while the TrustGate is actively evaluating candidates
- **THEN** the reader sees a consistent snapshot of log entries up to the point of read, without observing partial writes

#### Scenario: Trust decision idempotency under retry
- **WHEN** a TrustGate evaluation is retried due to a transient error
- **THEN** the retried evaluation produces the same decision as the original and does not create duplicate log entries

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

