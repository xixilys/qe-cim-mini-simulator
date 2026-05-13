## ADDED Requirements

### Requirement: Low-fidelity layer results are persisted with promotion decisions
The DSE workflow SHALL persist L1 and L2 layer outputs with explicit promotion decisions when they are used to decide whether a candidate enters L3/L4 simulation. Each persisted layer result SHALL include fidelity level, status, metrics, uncertainty or confidence, evaluator provenance, and candidate-generation role. Each persisted promotion decision SHALL identify source layer, target layer, threshold, score, confidence, decision, and reason.

#### Scenario: L1 and L2 decisions are auditable
- **WHEN** a selected Step2 candidate is screened before Step3
- **THEN** reviewers can inspect the L1 result, L1→L2 decision, L2 result, L2→L3 decision, and summary without rerunning Python process state

### Requirement: Step3 validates low-fidelity handoff completeness without running L1/L2
Step3 SHALL validate the presence and pass/fail status of required Step2 low-fidelity screening artifacts before constructing trusted L3/L4 evidence. Step3 SHALL NOT run L1 or L2 evaluators itself.

#### Scenario: Missing low-fidelity artifact blocks before simulation
- **WHEN** Step2 marks a candidate promoted but a required L1/L2 screening artifact is missing or the low-fidelity summary is not passed
- **THEN** Step3 returns `blocked_before_simulation` and records a machine-readable low-fidelity handoff reason
