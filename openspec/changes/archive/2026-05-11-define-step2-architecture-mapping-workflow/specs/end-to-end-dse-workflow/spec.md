## ADDED Requirements

### Requirement: End-to-end workflow has a Step2 architecture/mapping boundary
The end-to-end DSE workflow SHALL define Step2 as the boundary after workload package validation and graph lowering and before SystemC/gem5+SystemC simulation. Step2 SHALL produce architecture, DesignPoint, mapping, screening, promotion, and feedback-handoff artifacts consumed by later simulation/evidence/report stages.

#### Scenario: Step2 emits the handoff artifact set
- **WHEN** a workload passes Step1 validation and lowering
- **THEN** Step2 emits architecture catalog/instance artifacts, DesignPoint artifacts, mapping legality matrix, seed set, candidate records, selected mapping record, promotion/simulation queue information, feedback state, and convergence/budget status

#### Scenario: Step3 consumes Step2 without hidden state
- **WHEN** Step3+ simulation starts for a promoted candidate
- **THEN** it can reconstruct the simulation request from Step1 and Step2 persisted artifacts without relying on hidden Python process state

### Requirement: Step2 failure modes are visible in final workflow status
The workflow SHALL distinguish Step2 blocked states including unsupported graph lowering, invalid architecture, no legal mapping, missing binding, exhausted promotion budget, and diagnostic-only evidence. These states SHALL propagate to final report limitations and SHALL NOT be converted into successful full-flow completion claims.

#### Scenario: No legal mapping blocks simulation promotion
- **WHEN** Step2 cannot find a legal mapping for required executable graph nodes
- **THEN** the workflow records a blocked Step2 status and SHALL NOT submit an invalid mapping to trusted simulation

#### Scenario: Missing binding remains candidate-only
- **WHEN** Step2 finds a legal mapping on an architecture without trusted simulation binding
- **THEN** the workflow may keep the candidate for planning diagnostics but marks it candidate-only for final trusted claims
