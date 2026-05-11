## ADDED Requirements

### Requirement: High-fidelity feedback samples are multi-candidate artifacts
The multi-fidelity evaluator SHALL persist every promoted high-fidelity attempt in `mapping_simulation_samples.json`. Each sample SHALL include candidate id, backend, fidelity level, lifecycle status, trusted-final eligibility, metrics when available, evidence ids, and any blocker or missing-proof reason.

#### Scenario: Multiple promoted samples are recorded
- **WHEN** a DSE run promotes more than one architecture or mapping candidate to SystemC or gem5+SystemC
- **THEN** `mapping_simulation_samples.json` contains one sample record for each attempted promoted candidate with its metrics, trust label, and evidence ids

#### Scenario: Blocked high-fidelity attempt remains diagnostic
- **WHEN** a promoted gem5+SystemC or SystemC attempt fails, times out, lacks proof, or is otherwise untrusted
- **THEN** the sample is retained with `trusted_final_eligible` false and a blocker or missing-proof reason instead of being used in trusted ranking

### Requirement: Feedback state records ranking correction and simulation budget
The feedback loop SHALL persist `mapping_feedback_state.json` with screened, promoted, attempted, completed, trusted, blocked, and remaining sample counts. The state SHALL record how high-fidelity measurements changed ranking, calibration, pruning, promotion policy, or next-candidate selection.

#### Scenario: Trusted sample updates ranking state
- **WHEN** a SystemC or gem5+SystemC sample passes all trust gates
- **THEN** `mapping_feedback_state.json` records the sample as trusted feedback and records the ranking or calibration effect applied to later candidate selection

#### Scenario: Promotion budget exhaustion is explicit
- **WHEN** promoted candidates remain but the configured SystemC/gem5+SystemC budget is consumed
- **THEN** `mapping_feedback_state.json` records budget exhaustion and lists the unattempted or predicted-only candidates separately from trusted samples

### Requirement: Convergence status is machine-checkable
The evaluator SHALL emit `convergence_status.json` for feedback-loop runs. The artifact SHALL record configured criteria, thresholds, evaluated metric history, stop reason, convergence boolean, budget status, and limitations. Budget exhaustion SHALL NOT be reported as full convergence unless a configured convergence criterion also passed.

#### Scenario: Frontier or top-K stability stops the loop
- **WHEN** the configured trusted frontier or top-K stability criterion is satisfied across feedback iterations
- **THEN** `convergence_status.json` records `stop_reason` as convergence and includes the evidence-backed metric history used for the decision

#### Scenario: Budget exhaustion is not convergence
- **WHEN** simulation budget is exhausted before stability, improvement, uncertainty, or family-coverage criteria pass
- **THEN** `convergence_status.json` records budget exhaustion, `converged` false, and a limitation explaining that global optimality is not proven

### Requirement: Comparative ranking uses trusted samples only
Comparative architecture, mapping, and Pareto ranking SHALL use only candidates with trusted SystemC or gem5+SystemC samples and resolved evidence ids. Predicted-only, blocked, prototype, or stub-only candidates MAY appear in appendices but SHALL NOT become trusted winners or Pareto members.

#### Scenario: Predicted candidate is excluded from trusted Pareto set
- **WHEN** a candidate has only L1/L2/surrogate screening results and no trusted high-fidelity sample
- **THEN** it is excluded from trusted Pareto and winner claims and appears only as predicted-only or candidate-only evidence

#### Scenario: Trusted comparison cites every compared sample
- **WHEN** the final report compares two candidates on latency, power, energy, data movement, or Pareto dominance
- **THEN** every compared candidate links to its trusted sample evidence and unresolved evidence ids fail claim validation
