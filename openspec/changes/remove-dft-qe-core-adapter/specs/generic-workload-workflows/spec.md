## ADDED Requirements

### Requirement: Workflow templates become workload profiles
The system SHALL treat workload workflow templates as workload profiles. Existing workflow metadata fields SHALL remain available through the profile contract, and new implementations SHALL use profile terminology in public APIs, status artifacts, and tests.

#### Scenario: Registry exposes profiles
- **WHEN** a user or Step1 introspects supported workload behavior
- **THEN** the system returns workload profiles with accepted sources, lowering policy, mapping preferences, validation boundaries, unavailable metrics, and required coverage rules

#### Scenario: No workflow hardcodes DFT/QE as privileged
- **WHEN** the profile registry contains a QE reference profile
- **THEN** it is represented using the same fields as all other profiles and no core workflow function special-cases `dft_qe`

### Requirement: Required coverage resolution is profile-driven
Required coverage SHALL be resolved from explicit profile coverage first and from lowered executable graph nodes/regions second. Required coverage resolution SHALL NOT contain workload-family-specific fallback branches.

#### Scenario: QE coverage comes from profile
- **WHEN** the QE reference profile declares SCF coverage labels
- **THEN** coverage resolution returns those labels because they are profile data, not because the workload family name matches `dft_qe`

## MODIFIED Requirements

### Requirement: Workload families have explicit workflow templates
The system SHALL define workload profiles that describe accepted sources, importer output, graph semantics, lowering policy, mapping preferences, simulation coverage, domain validation, evidence artifacts, and final claim boundary for each supported family. Profiles SHALL be normative acceptance criteria for later importer implementation and SHALL NOT be implemented as hardcoded branches in core DSE orchestration.

#### Scenario: Workflow template drives adapter implementation
- **WHEN** a developer implements an importer for a supported family
- **THEN** the importer uses profile fields needed by the generic DSE pipeline rather than requiring new core schema fields

#### Scenario: Unknown family uses custom workflow declaration
- **WHEN** a user-defined scientific workload does not match a built-in family
- **THEN** it can still run by providing a custom profile declaration with source kind, coverage, lowering, mapping, validation, and claim-boundary metadata

### Requirement: Adapter-required coverage replaces global QE phase checks
Each workload profile SHALL declare required coverage as node ids, region ids, named phases, or executable-view tasks that must appear in timing evidence for a full-workload claim. Any QE SCF coverage SHALL be declared only by the selected QE reference profile; non-QE profiles SHALL NOT be checked against QE phase names unless they explicitly declare those names as their own profile coverage.

#### Scenario: Non-QE workload uses executable graph coverage
- **WHEN** an ML, sparse, stencil, graph analytics, database, or custom workload has no profile-specific coverage list
- **THEN** the workflow uses the lowered executable graph nodes or regions as required coverage for full-flow evidence

#### Scenario: DFT/QE keeps SCF coverage
- **WHEN** a QE reference profile declares canonical SCF coverage phases
- **THEN** the workflow records them as profile coverage, not as global core coverage or adapter-specific core logic

#### Scenario: Missing adapter coverage blocks trusted claims
- **WHEN** a required coverage item is absent from simulation events, summaries, or equivalent backend evidence
- **THEN** final trusted ranking, selected recommendation, and full-workload completion claims are blocked for that run

### Requirement: Workload-family final reports separate timing and domain claims
Final reports SHALL show for each workload profile: profile id/version, importer id/version, source provenance, claim boundary, required coverage, graph-lowering status, timing/resource evidence, unavailable metrics, profile-domain validation status, and limitations. A trusted timing run SHALL NOT automatically imply domain correctness for any family.

#### Scenario: Timing-only evidence remains scoped
- **WHEN** a workload has passing SystemC or gem5+SystemC timing evidence but no profile/importer-domain validator
- **THEN** the report may make timing/resource feasibility claims but labels domain correctness unavailable or unclaimed

#### Scenario: Reduced diagnostic workload cannot satisfy final check
- **WHEN** a workload package is reduced, sampled, imported-trace-only, synthetic regression, smoke-only, or diagnostic-only
- **THEN** final validation prevents it from satisfying trusted full-workload completion or winner claims
