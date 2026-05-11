## ADDED Requirements

### Requirement: Core IR rejects workload-family leakage
Core IR validation, serialization, mapping input generation, and backend request schemas SHALL remain workload-family neutral. Domain-specific node names, phase names, correctness labels, source parser fields, and preferred mapping targets SHALL be preserved as opaque adapter metadata or workflow metadata and SHALL NOT become required core fields.

#### Scenario: AI metadata remains opaque
- **WHEN** an ML/tensor adapter includes batch size, sequence length, layout, quantization policy, or model-output reference metadata
- **THEN** core IR preserves that metadata without adding ML-specific required fields to `ComputeGraph` or `WorkloadPackage`

#### Scenario: Scientific metadata remains opaque
- **WHEN** a scientific-computing adapter includes solver residuals, mesh shape, halo depth, timestep counts, sparse format, or QE `npw`/`nkb` values
- **THEN** core IR preserves that metadata without interpreting it outside adapter-owned validation

#### Scenario: Domain-specific required fields are rejected
- **WHEN** a core IR boundary requires fields such as QE SCF phases, ML accuracy labels, SQL query semantics, graph convergence labels, or sparse residual names for all workloads
- **THEN** validation reports domain leakage and the implementation must move that requirement into adapter/workflow metadata
