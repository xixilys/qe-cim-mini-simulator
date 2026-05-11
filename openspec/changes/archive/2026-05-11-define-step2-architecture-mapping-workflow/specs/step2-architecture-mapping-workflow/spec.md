## ADDED Requirements

### Requirement: Step2 consumes the Step1 generic workload handoff
Step2 SHALL begin only from validated Step1 artifacts: `workload_package.json`, source `workload_graph.json`, `graph_lowering_report.json`, optional `executable_graph.json`, workflow metadata, required coverage, and source-to-executable node or region mapping. Step2 SHALL consume generic graph nodes, edges, tensor specs, cost hints, workflow mapping-policy hooks, and claim-boundary metadata; it SHALL NOT require QE-specific fields or adapter-private state.

#### Scenario: Non-QE Step1 output enters Step2
- **WHEN** Step1 emits a lowered ML, sparse, stencil, graph analytics, database/vector-search, or custom workload package
- **THEN** Step2 can construct architecture and mapping candidates from generic node ids, op types, tensor sizes, workflow metadata, and required coverage without expecting QE phase names

#### Scenario: Unsupported lowering blocks Step2 trusted candidate generation
- **WHEN** `graph_lowering_report.json` has status `unsupported` or lacks a resolvable executable view for required coverage
- **THEN** Step2 records an unsupported-workload diagnostic and SHALL NOT promote a trusted architecture/mapping candidate for full-flow simulation

### Requirement: Step2 defines replayable architecture candidate artifacts
Step2 SHALL produce versioned architecture artifacts that identify catalog version, architecture family, parameter assignment, component instances, memory hierarchy, interconnect, constraints, simulation binding status, validation verdict, and trusted-final eligibility. Architecture candidates without executable binding MAY remain in screening, but SHALL be labeled candidate-only for final reporting.

#### Scenario: Bound architecture can become a simulation candidate
- **WHEN** an architecture instance has valid components, constraints, routes, required operator support or fallback, and executable SystemC or gem5+SystemC binding coverage
- **THEN** Step2 may mark it eligible for promotion to Step3+ simulation

#### Scenario: Unbound architecture remains candidate-only
- **WHEN** an architecture family or instance has planned, prototype, stub, missing, or unsupported simulation binding
- **THEN** Step2 may keep it in candidate diagnostics but SHALL mark it ineligible for trusted final ranking until binding validation passes

### Requirement: Step2 assembles complete DesignPoint records
Step2 SHALL assemble DesignPoint records that bind workload id, architecture instance id, selected mapping, data-placement policy, scheduling policy, precision policy, fallback policy, simulation config, evidence/output config, random seed, objective directions, and replay metadata. Hidden process state SHALL NOT be required to replay a promoted candidate.

#### Scenario: Promoted candidate is replayable
- **WHEN** a candidate is selected for SystemC or gem5+SystemC sampling
- **THEN** the persisted DesignPoint and mapping artifacts contain enough information to rebuild the same backend request deterministically

#### Scenario: Missing placement policy is explicit
- **WHEN** Step2 has not implemented separate data placement, schedule placement, or precision placement for a candidate
- **THEN** the DesignPoint records an explicit default or unavailable policy instead of relying on an undocumented implicit choice

### Requirement: Step2 constructs a legality matrix before search
Step2 SHALL construct `mapping_legality_matrix.json` before selecting mappings. The matrix SHALL record every executable graph node against every architecture resource or fallback target with legal/illegal status and machine-readable reasons including unsupported op, unsupported precision, memory capacity, missing route, missing binding, power/area budget, or forbidden placement.

#### Scenario: Illegal accelerator placement is rejected before simulation
- **WHEN** a node is mapped to an accelerator that cannot execute its `op_type` or precision
- **THEN** the legality matrix records the rejection reason and Step2 SHALL NOT promote that mapping as trusted-final eligible

#### Scenario: Host fallback is visible
- **WHEN** host fallback is used for an unsupported or high-risk node
- **THEN** the legality matrix and selected mapping record identify the fallback target and reason rather than silently treating it as accelerator execution

### Requirement: Step2 seed mappings are generic and workflow-aware
Step2 SHALL generate seed mappings from core generic policies and optional workload workflow policies. Core seeds SHALL include host baseline, capability-greedy, memory-locality, communication-aware, all-offload, streaming, batch, fallback-mixed, and debug-observable where applicable. Adapter or workflow seeds SHALL be labeled with adapter id or workload family and SHALL operate over generic node ids/op types rather than hardcoded core-domain node names.

#### Scenario: DFT/QE seed is adapter scoped
- **WHEN** a DFT/QE workflow supplies a hardware-diagonalization or operator-sweep seed
- **THEN** Step2 records it as adapter/workflow-owned metadata and SHALL NOT expose it as a global default for non-QE workloads

#### Scenario: Non-QE workflow seed uses generic operators
- **WHEN** a sparse, stencil, graph analytics, ML/tensor, database/vector-search, or custom workflow supplies default mapping policies
- **THEN** Step2 translates those policies into legal placements using generic op types, tensor sizes, and architecture capabilities

### Requirement: Step2 persists candidate lifecycle and promotion artifacts
Step2 SHALL persist mapping seed sets, candidate records, screening results, promotion decisions, selected mapping record, simulation sample queue or sample placeholders, feedback state, and convergence/budget status. The first implementation SHALL make the handoff concrete with `step2_status.json`, `mapping_promotion_decision.json`, and `step2_artifact_validation.json` in addition to the required mapping artifacts. Each candidate SHALL have a lifecycle state and transition reason such as generated, screened, promoted, scheduled-for-simulation, simulated, rejected, blocked, finalist, or selected.

#### Scenario: Promotion reason is auditable
- **WHEN** Step2 promotes a candidate to Step3+ simulation
- **THEN** the promotion artifact records the reason, score basis, uncertainty or exploration quota, required evidence, and budget impact

#### Scenario: Rejected candidate remains inspectable
- **WHEN** Step2 rejects a candidate because of legality, constraints, binding, or budget
- **THEN** the candidate record remains in the artifact set with rejection reasons and does not disappear from audit history

### Requirement: Step2 cannot create final trusted conclusions by itself
Step2 SHALL NOT report a final best architecture, trusted Pareto member, mapping comparison winner, or domain correctness conclusion from architecture/mapping generation or low-fidelity screening alone. Trusted final claims require later SystemC or gem5+SystemC full-flow evidence and final claim validation.

#### Scenario: Predicted-only winner is blocked
- **WHEN** Step2 screening predicts a candidate is best but no high-fidelity simulation evidence exists
- **THEN** reports may label it predicted-only or promoted-for-simulation, but SHALL NOT list it as a trusted winner

#### Scenario: Smoke or diagnostic path cannot satisfy Step2 handoff
- **WHEN** a candidate cites smoke-only, fixed-timing, driver hello, or diagnostic replay evidence as completion
- **THEN** Step2 marks it diagnostic-only and the final validator SHALL reject it as trusted completion evidence
