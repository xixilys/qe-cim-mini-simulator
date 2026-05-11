## ADDED Requirements

### Requirement: WorkloadPackage declares workload workflow metadata
A WorkloadPackage emitted by any adapter SHALL carry or reference workflow metadata sufficient for the generic DSE pipeline to determine required coverage, lowering policy, domain validation boundary, default mapping-policy hooks, and final claim boundary. The metadata SHALL remain adapter-owned and opaque to core domain semantics, but the generic pipeline SHALL be able to read standardized keys such as adapter id/version, claim boundary, required coverage, unsupported constructs, and validation artifact names.

#### Scenario: Adapter declares non-QE coverage
- **WHEN** an adapter emits an ML, sparse, stencil, graph analytics, database/vector-search, or custom workload
- **THEN** the package declares required coverage explicitly or allows the workflow to use lowered executable graph nodes as coverage without expecting QE phase names

#### Scenario: Domain metadata remains opaque
- **WHEN** a package contains family-specific metadata such as ML batch shape, sparse format, stencil halo, graph frontier policy, vector index type, query cardinality, or QE `npw`
- **THEN** core IR validation preserves that metadata and reads only standardized workflow keys needed for generic orchestration and claim gating

### Requirement: ComputeGraph coverage items resolve to graph entities
The ComputeGraph and graph-lowering artifacts SHALL allow adapter-required coverage items to resolve to source node ids, executable node ids, region ids, or summarized loop/stream constructs. Coverage items that cannot be resolved SHALL be reported before final trusted simulation claims are accepted.

#### Scenario: Region-level coverage resolves through lowering
- **WHEN** a workflow declares a loop, streaming pipeline, fused kernel, or hierarchical region as required coverage
- **THEN** graph lowering records how that source region maps to executable tasks, summary records, or backend-native events used by evidence validation

#### Scenario: Unresolvable coverage blocks final claim
- **WHEN** a required coverage id does not map to a source graph entity or executable-view entity
- **THEN** final trusted claim validation fails with an explicit missing coverage diagnostic
