## ADDED Requirements

### Requirement: Feedback-loop runs export convergence and budget artifacts
An end-to-end DSE run with feedback enabled SHALL export `mapping_simulation_samples.json`, `mapping_feedback_state.json`, and `convergence_status.json` in the run directory. The run manifest and final report SHALL reference these artifacts so the stop/continue decision is replayable.

#### Scenario: Run manifest links feedback artifacts
- **WHEN** a feedback-enabled DSE run completes or stops by budget/blocker
- **THEN** `manifest.json` or `artifact_manifest.json` lists the feedback sample, feedback state, and convergence status artifacts with retrievable run-local paths

#### Scenario: Partial feedback run remains auditable
- **WHEN** a DSE run stops before all promoted candidates have trusted high-fidelity samples
- **THEN** the run directory still contains the attempted samples, remaining budget state, stop reason, and limitations needed to understand why the result is partial

### Requirement: Final reports separate convergence, budget exhaustion, and trusted recommendation status
The final report SHALL include a convergence/budget section that distinguishes proven convergence, budget exhaustion, hard blockers, and incomplete or user-stopped runs. Recommendation status SHALL be derived from trusted comparative evidence, not from the existence of a single trusted pilot.

#### Scenario: Budget-exhausted run reports limitation
- **WHEN** the feedback loop stops because high-fidelity budget is exhausted before convergence criteria pass
- **THEN** the final report lists budget exhaustion as a limitation and does not claim a globally converged best architecture

#### Scenario: Single trusted sample is not a global winner
- **WHEN** exactly one trusted high-fidelity sample exists for a run
- **THEN** the final report may claim feasibility for that sample but does not claim cross-candidate best architecture or trusted Pareto frontier unless comparable trusted samples exist

### Requirement: Claim validation covers comparative and convergence claims
Claim validation SHALL reject trusted best-architecture, mapping-comparison, Pareto-frontier, and convergence claims unless the referenced feedback, convergence, and sample artifacts exist and contain enough trusted evidence for the claim type.

#### Scenario: Comparative claim with missing sample fails validation
- **WHEN** a trusted mapping-comparison or Pareto claim references a candidate without a resolved trusted sample artifact
- **THEN** `claim_validation.json` marks the claim untrusted and records the missing evidence reason

#### Scenario: Convergence claim requires convergence artifact
- **WHEN** a final report includes a trusted convergence claim
- **THEN** `claim_validation.json` verifies that `convergence_status.json` exists and that its stop reason and criteria support the claim

### Requirement: Replay instructions cover feedback-loop evidence
Replay metadata SHALL include the command, seed/configuration, promoted candidate budget, backend choice, evidence mode, and run directory needed to reproduce the feedback-loop evidence shape and trust labels.

#### Scenario: Feedback loop can be replayed
- **WHEN** a reviewer follows the final report replay instructions
- **THEN** the rerun can regenerate the workload, promoted-candidate set, simulation sample records, convergence status, and final claim-validation artifacts for the same configuration
