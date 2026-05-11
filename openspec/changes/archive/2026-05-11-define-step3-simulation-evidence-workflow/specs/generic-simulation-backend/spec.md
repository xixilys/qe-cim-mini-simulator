## ADDED Requirements

### Requirement: Backend requests preserve Step2 handoff provenance
GenericSystemCBackend request construction SHALL support replay from persisted Step2 workload, executable graph, architecture, DesignPoint, and mapping artifacts. Requests generated for Step3 SHALL identify that the Step2 handoff was present and SHALL preserve mapping and workflow coverage used for simulation.

#### Scenario: Request mapping matches Step2 DesignPoint
- **WHEN** Step3 builds a simulation request from a valid Step2 run directory
- **THEN** the request mapping matches the persisted Step2 DesignPoint or selected mapping artifact and the request records Step2 handoff provenance

#### Scenario: Request contains lowered executable graph
- **WHEN** Step3 receives a source graph with a lowered executable view
- **THEN** the backend request contains the executable graph nodes and edges used by mapping and simulation, with provenance linking back to the Step2 handoff

### Requirement: Backend evidence remains full-flow gated
The generic backend SHALL NOT allow smoke, fixed-timing bring-up, diagnostic replay, prototype, or missing-binding execution to masquerade as Step3 trusted full-flow evidence. Such outputs SHALL be labeled diagnostic, blocked, or untrusted unless the full evidence contract and applicable L3/L4 proof pass.

#### Scenario: Diagnostic backend output is not trusted evidence
- **WHEN** a backend output comes from a smoke, diagnostic, fixed-timing, or prototype path
- **THEN** Step3 evidence and claim validation mark it untrusted for final ranking even if a command exits successfully

#### Scenario: Full-flow SystemC output can become trusted L3 evidence
- **WHEN** the standalone SystemC backend runs the selected full WorkloadPackage, produces complete request/result/evidence artifacts, and passes verdict plus claim validation
- **THEN** the sample may be labeled trusted L3 SystemC evidence while recording that L4 gem5 proof is not applicable
