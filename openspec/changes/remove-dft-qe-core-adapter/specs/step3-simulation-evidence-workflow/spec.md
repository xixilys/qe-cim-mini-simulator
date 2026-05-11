## ADDED Requirements

### Requirement: Step3 validates coverage from profile metadata
Step3 SHALL validate simulation coverage using required coverage carried from the resolved workload profile and graph lowering artifacts. Step3 SHALL NOT emit or require QE-specific coverage fields in the generic evidence schema.

#### Scenario: Generic coverage validation passes
- **WHEN** simulation evidence covers every required profile coverage item or lowered executable node/region
- **THEN** Step3 may mark coverage validation as passed regardless of workload family

#### Scenario: QE coverage appears only as profile coverage
- **WHEN** a QE reference profile declares SCF phase coverage
- **THEN** Step3 records those labels under generic required coverage fields and does not emit `required_qe_scf_phases` as a generic field

### Requirement: Domain validation remains profile/importer owned
Step3 SHALL distinguish generic timing/resource evidence from profile/importer-owned domain validation evidence.

#### Scenario: Missing domain validation blocks only domain claims
- **WHEN** timing evidence is complete but profile-required domain validation artifacts are absent
- **THEN** Step3 may pass timing/resource evidence while marking domain correctness unavailable or blocked

## MODIFIED Requirements

### Requirement: Step3 reconstructs a replayable simulation request from disk
Step3 SHALL rebuild the backend request using persisted workload package, executable graph, architecture, DesignPoint, selected mapping, profile metadata, importer metadata, scheduling/output configuration, and Step2 promotion metadata. The request SHALL include enough provenance to show that Step2 handoff artifacts were present and used.

#### Scenario: Valid handoff produces simulation_request
- **WHEN** Step3 receives a valid promoted Step2 handoff and the configured backend executable is available
- **THEN** it writes `simulation_request.json` containing workload nodes, edges, architecture resources, mapping, profile/importer metadata, scheduling/output fields, and Step2 handoff provenance

#### Scenario: Non-QE request remains domain-neutral
- **WHEN** Step3 runs a sparse, ML/tensor, stencil, graph analytics, database/vector-search, or custom non-QE workload
- **THEN** the request and final report do not require QE-only fields such as `npw`, `nkb`, `h_psi`, `s_psi`, `diagonalize`, `mix_rho`, or `veff`

#### Scenario: DFT/QE request preserves adapter boundary
- **WHEN** Step3 runs a QE reference profile/importer workflow
- **THEN** QE-specific coverage appears only as profile/importer metadata and does not become a required global field for other workload families

### Requirement: Step3 cross-step validation covers generic and adapter-specific workflows
Step3 implementation validation SHALL include tests that start from Step1 workload/package generation, run Step2 artifact emission, and then run Step3 simulation/evidence or blocked-handoff checks. Tests SHALL cover representative non-QE profiles and a QE reference profile/importer regression through the same generic path.

#### Scenario: Generic sparse workflow passes without QE assumptions
- **WHEN** a sparse linear-algebra workload runs through Step1, Step2, and Step3
- **THEN** Step3 emits trusted full-flow evidence and the request/report contain generic sparse coverage rather than QE-only phase requirements

#### Scenario: Database vector-search workflow passes without QE assumptions
- **WHEN** a database/vector-search workload runs through Step1, Step2, and Step3
- **THEN** Step3 emits trusted full-flow evidence and no QE-only required phases are introduced

#### Scenario: DFT/QE regression keeps adapter-scoped seeds and coverage
- **WHEN** a QE reference workload runs through Step1, Step2, and Step3
- **THEN** QE seed preferences and required coverage remain profile-scoped and do not rename or expose old QE-domain global defaults
