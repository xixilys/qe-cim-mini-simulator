# generic-dse-ir-contract Specification

## Purpose
Define the versioned IR contracts for generic DSE workloads, tasks, architecture references, tensors, data movement, execution timelines, serialization, and validation across Python, SystemC, and gem5 integration boundaries.
## Requirements
### Requirement: WorkloadPackage is the domain-neutral ingestion unit
The system SHALL ingest every workload through a versioned WorkloadPackage that wraps a ComputeGraph with source provenance, profile/importer identity, constraints, calibration references, and opaque domain metadata. Core DSE stages SHALL depend on the generic package and graph contract, not on QE, ML, database, sparse, stencil, or any other domain-specific fields.

#### Scenario: Non-DFT workload enters through the same package
- **WHEN** a workload importer emits an ML tensor graph, sparse linear algebra graph, stencil pipeline, graph analytics workload, database/vector-search pipeline, or user-defined scientific computation graph
- **THEN** the package is accepted when it contains valid generic graph nodes, edges, tensor/resource metadata, cost hints or cost-model bindings, provenance, and profile/importer identity

#### Scenario: Domain metadata stays opaque to core DSE
- **WHEN** a package carries profile/importer metadata such as QE `npw`, ML batch size, sparse matrix format, stencil halo depth, or query shape
- **THEN** core IR validation preserves the metadata but does not require or interpret it unless a profile/importer-specific validator is invoked

### Requirement: Workload profile/importer registry separates domain import from core IR
The system SHALL route workload ingestion through a registry of WorkloadImporter implementations. Each importer SHALL declare supported source kinds, importer version, emitted WorkloadPackage schema, and validation rules; workload profiles SHALL declare mapping policies, domain metrics, coverage, and claim boundary. Adding a new importer/profile SHALL NOT require changing core IR classes or generic backend request schemas. Core IR validation SHALL NOT contain hardcoded checks for domain-specific node names, phase templates, or operator enums.

#### Scenario: New workload importer is added without core schema changes
- **WHEN** a developer adds an importer/profile pair for a new workload family such as ONNX/ML, stencil, sparse linear algebra, graph analytics, streaming pipeline, dynamic-control workload, or custom JSON graph
- **THEN** it can emit WorkloadPackage and ComputeGraph artifacts consumed by architecture generation, mapping search, simulation, and reporting without QE-specific fields

#### Scenario: Reduced or diagnostic workload is labeled non-final
- **WHEN** an importer emits a reduced, sampled, synthetic, imported-trace-only, or diagnostic workload
- **THEN** the WorkloadPackage records that claim boundary and final validation prevents it from satisfying full-workload completion evidence

#### Scenario: Core IR rejects domain-specific node name checks
- **WHEN** core IR validation encounters a check for QE-specific node names (e.g., `h_psi`, `s_psi`, `diagonalize`, `mix_rho`, `veff`)
- **THEN** validation fails with `domain_leakage_error` because core IR must remain domain-neutral

#### Scenario: Core mapping search uses generic node properties
- **WHEN** mapping search processes a ComputeGraph
- **THEN** it uses generic properties (`op_type`, `tensor_specs`, `estimated_flops`) rather than hardcoded QE phase names or node ids

#### Scenario: Profile policy is scoped to profile
- **WHEN** a DFT/QE profile provides mapping policies
- **THEN** those policies are registered under the profile/importer namespace and are only applied when the DFT/QE reference profile/importer is explicitly selected

### Requirement: Versioned four-level IR stack
The system SHALL expose a versioned four-level IR stack with L3 Compute Graph, L2 Task Graph, L1 Architecture reference, and L0 Execution Timeline contracts. Each IR object SHALL carry enough identity and schema information to be serialized, compared, and validated across Python and simulation backends.

#### Scenario: IR object declares its contract version
- **WHEN** an IR object is serialized for DSE evaluation or backend execution
- **THEN** the serialized object contains a stable object identifier and an IR/schema version that downstream consumers can validate

#### Scenario: Unsupported IR version is rejected
- **WHEN** a backend receives an IR/schema version it does not support
- **THEN** the backend returns a structured incompatibility error instead of silently interpreting the payload

#### Scenario: Missing schema version is rejected
- **WHEN** an IR object is deserialized and lacks a `schema_version` field
- **THEN** deserialization fails with `schema_version_missing` error and the object is not used

#### Scenario: Schema version mismatch blocks evaluation
- **WHEN** `ComputeGraph.from_dict()` or `WorkloadPackage.from_dict()` receives a dict with `schema_version` that does not match the expected version
- **THEN** the method raises `SchemaVersionError` with expected and actual versions, and evaluation does not proceed

#### Scenario: Schema version is validated at every boundary
- **WHEN** an IR object crosses a boundary (Step1→Step2, Step2→Step3, Python→C++)
- **THEN** the receiving side validates the schema version before processing; mismatches are reported as structured errors

### Requirement: ComputeGraph is operator-agnostic and graph-shape neutral
The ComputeGraph SHALL represent an application workload as a domain-neutral computation graph of ComputeNode objects, typed dependency edges, and optional graph regions without requiring a predefined operator enum or a QE-specific phase template. Operator-specific information SHALL be carried in `op_type` and extensible attributes. The model SHALL support DAGs, hierarchical subgraphs, loops, streaming feedback, stateful nodes, and control-flow constructs when their semantics are explicitly declared.

#### Scenario: Custom operator is accepted with attributes
- **WHEN** a workload contains a ComputeNode with an unknown but non-empty `op_type` and valid tensor/resource attributes
- **THEN** the graph loader accepts the node as a generic operator and preserves its attributes for evaluators

#### Scenario: Unannotated dependency cycle is rejected
- **WHEN** ComputeGraph validation detects a cycle with no declared loop, feedback, streaming, or state semantics
- **THEN** validation fails with a structured error identifying the participating node ids and the missing semantic annotation

#### Scenario: Declared loop or feedback graph is accepted
- **WHEN** a ComputeGraph contains a loop, feedback edge, streaming recurrence, or control-flow region with bounds, convergence criteria, trace-derived trip counts, or a profile/importer-provided summary model
- **THEN** core IR validation accepts the graph and records the declared semantics for graph lowering and claim-boundary checks

#### Scenario: Hierarchical graph preserves subgraph identity
- **WHEN** an importer emits a fused kernel, loop body, pipeline stage, or reusable subgraph region
- **THEN** the ComputeGraph preserves both the region identity and the contained node/edge ids so mapping, lowering, and reporting can cite either level

### Requirement: TensorSpec defines units, shape, dtype, and layout
TensorSpec SHALL define tensor shape, dtype, layout, element count, and byte size using explicit units. Unknown dtypes SHALL be rejected unless the caller provides an explicit byte width extension.

#### Scenario: Tensor byte size is computed deterministically
- **WHEN** a TensorSpec has shape `(1024, 64)`, dtype `FP64`, and row-major layout
- **THEN** `size_bytes` is computed as `1024 * 64 * 8` and the layout is preserved in serialization

#### Scenario: Unknown dtype without width is invalid
- **WHEN** a TensorSpec uses dtype `CUSTOM16` without an explicit byte-width extension
- **THEN** validation reports an unsupported dtype error rather than assuming FP64 or zero bytes

### Requirement: ComputeNode records cost estimates and domain metadata
A ComputeNode SHALL record inputs, outputs, input/output TensorSpecs, estimated FLOPs, estimated memory bytes, and opaque attributes. The system SHALL distinguish framework-required fields from domain metadata.

#### Scenario: Missing required cost fields are reported
- **WHEN** a ComputeNode lacks both estimated FLOPs and an evaluator-specific cost model binding
- **THEN** the evaluator reports an insufficient-cost-model error for that node

#### Scenario: Domain metadata is preserved
- **WHEN** a DFT node includes attributes such as `qe_kernel`, `k_point`, or `spin_channel`
- **THEN** generic IR serialization preserves those attributes without requiring core IR changes

### Requirement: Typed graph edges carry data, control, state, and ordering semantics
Graph edges SHALL identify source node, target node, edge kind, optional tensor name, and optional TensorSpec or state/control metadata. DataEdge remains the data-dependency specialization. Validation SHALL ensure referenced nodes exist and tensor names are consistent with node outputs/inputs when such lists are declared.

#### Scenario: Edge references missing node
- **WHEN** an edge references a source or target node id absent from the graph
- **THEN** ComputeGraph validation rejects the graph and reports the missing id

#### Scenario: Edge tensor is used for communication modeling
- **WHEN** an edge includes a TensorSpec with byte size
- **THEN** TaskGraph mapping and backend request generation use that byte size for data movement estimation

#### Scenario: Control or state edge affects schedule without fake tensors
- **WHEN** a workload has an ordering, branch, state update, or side-effect dependency without tensor payload
- **THEN** the graph records a typed non-data edge and the scheduler respects it without inventing misleading zero-byte tensors

### Requirement: Graph lowering produces executable views without losing claim boundaries
Before a ComputeGraph is evaluated by a scheduler, L1/L2 evaluator, standalone SystemC backend, or gem5+SystemC path, the workflow SHALL lower it into an executable view such as a TaskGraph, unrolled bounded region, summarized loop model, or backend-supported streaming representation. The lowering artifact SHALL preserve links to source graph ids, declare approximations, and state whether the lowered view is full-workload eligible or reduced/diagnostic.

#### Scenario: Bounded loop lowers to executable tasks
- **WHEN** a graph contains a loop region with a declared iteration count or trace-derived trip-count distribution
- **THEN** lowering either expands or summarizes the loop, records the policy in `graph_lowering_report.json`, and exposes an executable view to mapping and simulation

#### Scenario: Unsupported dynamic graph fails before final evidence
- **WHEN** a graph contains dynamic control, recursion, data-dependent iteration, or stateful behavior that no profile/importer or backend can lower or summarize
- **THEN** the workflow returns an unsupported-graph diagnostic and prevents final trusted simulation or reporting claims for that workload

### Requirement: TaskGraph captures placement, scheduling, dependencies, and movement
The TaskGraph SHALL represent mapped work units with placement, schedule, dependencies, resource requirements, and data movement records. It SHALL support tasks derived from single ComputeNodes or fused subgraphs.

#### Scenario: Fused task preserves source nodes
- **WHEN** two ComputeGraph nodes are fused into one Task
- **THEN** the Task records the source node ids and preserves external dependencies entering or leaving the fused region

#### Scenario: Task without placement is not executable
- **WHEN** a TaskGraph is submitted to an evaluator and a Task has no accelerator placement
- **THEN** the evaluator marks the design point infeasible or requests a mapping step before execution

### Requirement: Data movement timing uses explicit bandwidth and latency units
DataMovement SHALL compute transfer latency from bytes, bandwidth in Gbps, and fixed latency in milliseconds using a single documented formula. Unit conversions SHALL be covered by tests.

#### Scenario: Transfer time formula is applied correctly
- **WHEN** a DataMovement moves `size_bytes` over `bandwidth_gbps` with `latency_ms`
- **THEN** transfer time is `size_bytes * 8 / (bandwidth_gbps * 1e9) * 1000 + latency_ms`

#### Scenario: Invalid bandwidth is rejected
- **WHEN** data movement bandwidth is zero or negative
- **THEN** validation fails instead of producing infinite, negative, or silently clamped timing unless an explicit fallback policy is declared

### Requirement: ExecutionTimeline records auditable events and resources
The ExecutionTimeline SHALL record ordered execution events, resource usage samples, data transfers, and summary metrics. Events SHALL reference task ids and accelerator ids that exist in the evaluated design point.

#### Scenario: Timeline summary is reproducible
- **WHEN** an evaluator returns an ExecutionTimeline
- **THEN** makespan, total data movement, and utilization summaries can be recomputed from recorded events and transfers

#### Scenario: Orphan event is rejected
- **WHEN** a timeline event references an unknown task id or accelerator id
- **THEN** result validation reports the orphan reference before accepting the evaluation result

### Requirement: IR serialization round-trips without semantic loss
All IR layers SHALL support deterministic serialization to dictionaries/JSON and deserialization or reconstruction sufficient for tests to compare semantic equality. Extension fields SHALL be preserved unless explicitly filtered by a schema version.

#### Scenario: Round-trip preserves graph semantics
- **WHEN** a ComputeGraph is serialized and loaded back through the supported contract
- **THEN** node ids, edge ids, tensor specs, operator types, and attributes are equivalent to the original graph

#### Scenario: Unknown extension is preserved
- **WHEN** an IR object contains an extension field under a namespaced key
- **THEN** serialization round-trip preserves that field for downstream consumers

### Requirement: IR validation reports structured errors
The IR layer SHALL return structured validation errors with object type, object id, field, severity, and message. It SHALL NOT hide invalid inputs by replacing them with generic defaults.

#### Scenario: Multiple validation errors are reported together
- **WHEN** a graph contains more than one independent invalid field
- **THEN** validation reports all detected errors in one result so users can repair the graph efficiently

#### Scenario: Evaluation stops on fatal IR error
- **WHEN** a fatal IR validation error is present
- **THEN** DSE evaluation does not proceed to ranking or backend invocation for that design point

### Requirement: Core IR rejects workload-family leakage
Core IR validation, serialization, mapping input generation, and backend request schemas SHALL remain workload-family neutral. Domain-specific node names, phase names, correctness labels, source parser fields, and preferred mapping targets SHALL be preserved as opaque profile/importer metadata or workflow metadata and SHALL NOT become required core fields.

#### Scenario: AI metadata remains opaque
- **WHEN** an ML/tensor importer/profile includes batch size, sequence length, layout, quantization policy, or model-output reference metadata
- **THEN** core IR preserves that metadata without adding ML-specific required fields to `ComputeGraph` or `WorkloadPackage`

#### Scenario: Scientific metadata remains opaque
- **WHEN** a scientific-computing importer/profile includes solver residuals, mesh shape, halo depth, timestep counts, sparse format, or QE `npw`/`nkb` values
- **THEN** core IR preserves that metadata without interpreting it outside profile/importer-owned validation

#### Scenario: Domain-specific required fields are rejected
- **WHEN** a core IR boundary requires fields such as QE SCF phases, ML accuracy labels, SQL query semantics, graph convergence labels, or sparse residual names for all workloads
- **THEN** validation reports domain leakage and the implementation must move that requirement into profile/workflow metadata

