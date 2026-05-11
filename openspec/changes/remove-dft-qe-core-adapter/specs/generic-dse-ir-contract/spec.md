## ADDED Requirements

### Requirement: Core IR uses profile and importer metadata instead of adapter metadata
The WorkloadPackage and ComputeGraph contracts SHALL identify workload source translation through importer metadata and workload semantics through profile metadata. Core IR SHALL NOT require adapter classes, adapter-owned coverage constants, or domain-specific adapter ids to interpret generic workload artifacts.

#### Scenario: Package carries profile and importer identity
- **WHEN** an importer emits a WorkloadPackage
- **THEN** the package records importer id/version and profile id/version while preserving source and domain metadata as opaque fields

#### Scenario: Core rejects privileged workload-family branches
- **WHEN** core IR validation, mapping input generation, backend request generation, or reporting requires a branch for `dft_qe`, QE phase names, or any other workload-family-specific identifier
- **THEN** the implementation violates the IR contract and must move that behavior into profile/importer data

## MODIFIED Requirements

### Requirement: WorkloadPackage is the domain-neutral ingestion unit
The system SHALL ingest every workload through a versioned WorkloadPackage that wraps a ComputeGraph with source provenance, importer identity, profile identity, constraints, calibration references, and opaque domain metadata. Core DSE stages SHALL depend on the generic package, graph, importer metadata, and profile metadata contracts, not on QE, ML, database, sparse, stencil, or any other domain-specific fields.

#### Scenario: Non-DFT workload enters through the same package
- **WHEN** a workload importer emits an ML tensor graph, sparse linear algebra graph, stencil pipeline, graph analytics workload, database/vector-search pipeline, or user-defined scientific computation graph
- **THEN** the package is accepted when it contains valid generic graph nodes, edges, tensor/resource metadata, cost hints or cost-model bindings, provenance, importer identity, and profile identity

#### Scenario: Domain metadata stays opaque to core DSE
- **WHEN** a package carries profile/importer metadata such as QE `npw`, ML batch size, sparse matrix format, stencil halo depth, or query shape
- **THEN** core IR validation preserves the metadata but does not require or interpret it unless a profile/importer-specific validator is invoked

### Requirement: Workload adapter registry separates domain import from core IR
The system SHALL route workload ingestion through separate registries of WorkloadProfile definitions and WorkloadImporter implementations. Each importer SHALL declare supported source kinds, importer version, compatible profiles, emitted WorkloadPackage schema, validation rules, and provenance behavior. Adding a new importer or profile SHALL NOT require changing core IR classes or generic backend request schemas. Core IR validation SHALL NOT contain hardcoded checks for domain-specific node names, phase templates, operator enums, adapter ids, or workload-family ids.

#### Scenario: New workload importer is added without core schema changes
- **WHEN** a developer adds an importer for a new source format such as ONNX/ML, stencil DSL, sparse matrix, graph trace, query plan, streaming pipeline, dynamic-control workload, or custom JSON graph
- **THEN** it can emit WorkloadPackage and ComputeGraph artifacts consumed by architecture generation, mapping search, simulation, and reporting without QE-specific fields

#### Scenario: Reduced or diagnostic workload is labeled non-final
- **WHEN** an importer emits a reduced, sampled, synthetic, imported-trace-only, or diagnostic workload
- **THEN** the WorkloadPackage records that claim boundary and final validation prevents it from satisfying full-workload completion evidence

#### Scenario: Core IR rejects domain-specific node name checks
- **WHEN** core IR validation encounters a check for QE-specific node names (e.g., `h_psi`, `s_psi`, `diagonalize`, `mix_rho`, `veff`)
- **THEN** validation fails with `domain_leakage_error` because core IR must remain domain-neutral

#### Scenario: Core mapping search uses generic node properties
- **WHEN** mapping search processes a ComputeGraph
- **THEN** it uses generic properties (`op_type`, `tensor_specs`, `estimated_flops`) and profile-supplied preferences rather than hardcoded QE phase names or node ids

#### Scenario: Profile policy is scoped to profile
- **WHEN** a workload profile provides mapping preferences
- **THEN** those preferences are registered under the profile namespace and are only applied when that profile is explicitly selected
