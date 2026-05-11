## ADDED Requirements

### Requirement: Step3 samples are the trusted high-fidelity feedback boundary
The multi-fidelity evaluator SHALL treat Step3 SystemC or gem5+SystemC evidence as the first eligible source for trusted high-fidelity feedback samples. L1/L2/surrogate predictions, Step2 screening, smoke, diagnostic, prototype, candidate-only, or blocked samples SHALL remain non-final and SHALL NOT update trusted ranking as measured winners.

#### Scenario: Trusted Step3 sample updates feedback state
- **WHEN** Step3 emits `trusted_full_flow_evidence_emitted` with resolved evidence ids
- **THEN** `mapping_simulation_samples.json`, `mapping_feedback_state.json`, and later convergence/reporting artifacts may count that sample as trusted high-fidelity feedback

#### Scenario: Blocked Step3 sample remains auditable but non-final
- **WHEN** Step3 blocks before simulation or completes with untrusted evidence
- **THEN** feedback state records the blocker or evidence gap and the sample SHALL NOT enter trusted Pareto, winner, or convergence claims

### Requirement: Comparative and convergence claims require multiple resolved Step3 samples when applicable
Multi-candidate ranking, Pareto, mapping-comparison, and convergence claims SHALL be based on comparable trusted Step3 samples and the corresponding feedback/convergence artifacts. A single trusted Step3 pilot MAY support feasibility for that design point, but SHALL NOT by itself prove a global winner or converged frontier.

#### Scenario: Single trusted sample is not a global winner
- **WHEN** exactly one candidate has trusted Step3 full-flow evidence
- **THEN** the final report may claim that candidate's feasibility/timing evidence but does not claim a globally best architecture, trusted Pareto frontier, or converged mapping search

#### Scenario: Comparative claim cites all compared Step3 samples
- **WHEN** a final report compares two architectures or mappings
- **THEN** every compared item links to its trusted Step3 evidence and unresolved or untrusted Step3 samples fail claim validation
