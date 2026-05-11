## ADDED Requirements

### Requirement: WorkloadProfile is the declarative workload contract
The system SHALL define `WorkloadProfile` as the declarative contract for workload-family behavior. A profile SHALL contain a stable profile id/version, accepted source kinds, graph pattern, lowering policy, required coverage rules, mapping preferences, unavailable metrics, domain validation requirements, default claim boundary, and optional plugin metadata.

#### Scenario: Core consumes profile data generically
- **WHEN** Step1 resolves a workload profile
- **THEN** Step1, Step2, Step3, backend request generation, and reporting consume the profile fields generically without branching on workload-family names such as `dft_qe`

#### Scenario: Missing coverage derives from executable graph
- **WHEN** a workload profile does not declare explicit required coverage
- **THEN** required coverage is derived from lowered executable graph nodes or regions

### Requirement: Profiles own workload-specific policy and wording
Workload-specific mapping preferences, coverage labels, unavailable metrics, correctness requirements, and limitation wording SHALL live in `WorkloadProfile` data. Core DSE modules SHALL NOT define workload-family constants for these policies.

#### Scenario: QE coverage is profile data
- **WHEN** a QE reference workload requires SCF phase coverage
- **THEN** those phase names appear in the QE reference profile data and not as a core constant or core validation branch

#### Scenario: Non-QE profile has independent semantics
- **WHEN** an ML, sparse, graph, database, stencil, or custom profile is selected
- **THEN** its coverage, mapping preferences, unavailable metrics, and domain validation text do not inherit QE profile values
