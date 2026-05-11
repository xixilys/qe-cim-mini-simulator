## ADDED Requirements

### Requirement: End-to-end workflow is profile-driven
The end-to-end DSE workflow SHALL carry profile id/version and importer id/version from Step1 through mapping, simulation, evidence, reporting, and replay metadata. No stage SHALL require a privileged workload-family branch to complete a run.

#### Scenario: Non-QE and QE reference use same flow
- **WHEN** a non-QE workload and a QE reference workload both produce valid WorkloadPackage and ComputeGraph artifacts
- **THEN** both runs proceed through the same generic Step1, Step2, Step3, and reporting stages with profile-specific behavior supplied as data

#### Scenario: Final report states profile boundary
- **WHEN** the final report summarizes any run
- **THEN** it reports profile id/version, importer id/version, claim boundary, required coverage, domain validation status, and limitations without workload-family-specific schema fields

## MODIFIED Requirements

### Requirement: Pipeline stages have explicit inputs and outputs
The end-to-end workflow SHALL define stable stage boundaries for workload ingestion, design-space generation, mapping search, simulation scheduling, evidence collection, result aggregation, and report generation. Each stage SHALL persist enough artifacts for replay or debugging, including profile/importer metadata when workload ingestion is involved.

#### Scenario: Stage output feeds next stage
- **WHEN** workload ingestion completes
- **THEN** it emits a WorkloadPackage and workload graph artifact consumed by architecture/mapping stages without hidden in-memory-only state

#### Scenario: Workload ingestion is adapter-based
- **WHEN** a user selects a supported workload profile and compatible importer
- **THEN** the importer emits a domain-neutral WorkloadPackage/ComputeGraph pair with profile identity, importer identity, source provenance, claim boundary, and optional domain metadata

#### Scenario: Arbitrary computation graph is normalized before mapping
- **WHEN** the emitted ComputeGraph contains loops, control-flow regions, streaming feedback, hierarchical subgraphs, or stateful nodes
- **THEN** the workflow produces a graph lowering report and an executable view for mapping/simulation, while preserving links to the original graph ids and claim boundary

#### Scenario: Failed stage preserves diagnostics
- **WHEN** any pipeline stage fails
- **THEN** the run directory contains the stage name, input artifact ids, error message, and partial outputs needed for debugging

### Requirement: Mapping search is algorithmic and constraint-aware
The system SHALL search mapping choices algorithmically using legality matrices, generic seed mappings, profile-provided mapping preferences, pruning, local or beam search, and SystemC-gated finalist evaluation. Manual fixed mappings MAY be used as baselines but SHALL NOT be the only mapping strategy. Core mapping search SHALL reason over generic node ids, op types, tensor sizes, resource capabilities, and profile policy hooks rather than hardcoded QE node names.

#### Scenario: Legality matrix filters invalid placements
- **WHEN** a workload operator is unsupported by a hardware resource or violates memory/precision constraints
- **THEN** mapping search excludes that placement or records it as illegal before simulation

#### Scenario: Search proposes improved mappings
- **WHEN** the mapping optimizer evaluates candidate mappings under the same architecture and workload
- **THEN** it can produce ranked alternatives with differences in latency, data movement, utilization, or constraint satisfaction

#### Scenario: Adapter policy augments generic seeds
- **WHEN** a workload profile supplies domain-specific seed policies
- **THEN** mapping search records the profile policy id and treats the seed as a suggestion over generic ComputeGraph nodes, while preserving legality and final simulation gates

#### Scenario: Mapping search uses lowered executable graph
- **WHEN** a source ComputeGraph has declared loops, regions, dynamic control, or streaming recurrences
- **THEN** the mapping optimizer uses the normalized executable graph or summarized region view and records source-to-executable graph correspondence in persisted mapping artifacts
