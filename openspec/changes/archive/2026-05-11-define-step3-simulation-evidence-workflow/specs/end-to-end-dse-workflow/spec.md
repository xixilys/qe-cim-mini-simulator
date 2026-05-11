## ADDED Requirements

### Requirement: End-to-end workflow has a Step3 simulation/evidence boundary
The end-to-end DSE workflow SHALL define Step3 as the boundary after Step2 architecture/mapping promotion and before feedback/reporting can use high-fidelity evidence. Step3 SHALL consume persisted Step2 artifacts, perform pre-simulation trust checks, run SystemC or gem5+SystemC when eligible, and emit simulation/evidence/report artifacts for later feedback and final claim validation.

#### Scenario: Step3 consumes Step2 without hidden state
- **WHEN** Step3 starts from a promoted Step2 candidate
- **THEN** it reconstructs the backend request from the run-directory artifact set rather than from hidden in-memory state

#### Scenario: Step3 blocked state propagates to final workflow status
- **WHEN** Step3 blocks before simulation because of missing artifacts, unsupported lowering, diagnostic claim boundary, illegal mapping, or missing binding
- **THEN** the overall workflow records a blocked or untrusted state and SHALL NOT report the candidate as a trusted final result

#### Scenario: Step3 evidence feeds feedback and reports
- **WHEN** Step3 emits trusted full-flow evidence
- **THEN** later feedback, convergence, and final-report stages can reference the Step3 evidence ids and manifests as the high-fidelity sample source

### Requirement: Cross-step tests prove Step1 to Step2 to Step3 continuity
The implementation validation SHALL include tests that execute the workflow across Step1 workload packaging/lowering, Step2 architecture/mapping artifact emission, and Step3 simulation/evidence production or blocked-handoff status. Stage-local tests SHALL NOT be the only evidence for Step3 completion.

#### Scenario: Non-QE full flow is tested end to end
- **WHEN** a non-QE workload family is selected for Step3 validation
- **THEN** the test starts from Step1 package creation, runs Step2 mapping, runs Step3, and asserts final evidence without QE-only required fields

#### Scenario: DFT/QE full flow is tested as an adapter regression
- **WHEN** the DFT/QE adapter is selected for Step3 validation
- **THEN** the test verifies that adapter-required coverage survives the Step1→Step2→Step3 path while remaining separate from generic core requirements
