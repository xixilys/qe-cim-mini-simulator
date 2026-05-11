## ADDED Requirements

### Requirement: Versioned four-level IR stack
The system SHALL expose a versioned four-level IR stack with L3 Compute Graph, L2 Task Graph, L1 Architecture reference, and L0 Execution Timeline contracts. Each IR object SHALL carry enough identity and schema information to be serialized, compared, and validated across Python and simulation backends.

#### Scenario: IR object declares its contract version
- **WHEN** an IR object is serialized for DSE evaluation or backend execution
- **THEN** the serialized object contains a stable object identifier and an IR/schema version that downstream consumers can validate

#### Scenario: Unsupported IR version is rejected
- **WHEN** a backend receives an IR/schema version it does not support
- **THEN** the backend returns a structured incompatibility error instead of silently interpreting the payload

### Requirement: ComputeGraph is operator-agnostic and dependency-safe
The ComputeGraph SHALL represent an application workload as a directed acyclic graph of ComputeNode and DataEdge objects without requiring a predefined operator enum. Operator-specific information SHALL be carried in `op_type` and extensible attributes.

#### Scenario: Custom operator is accepted with attributes
- **WHEN** a workload contains a ComputeNode with an unknown but non-empty `op_type` and valid tensor/resource attributes
- **THEN** the graph loader accepts the node as a generic operator and preserves its attributes for evaluators

#### Scenario: Cyclic dependency is rejected
- **WHEN** ComputeGraph validation detects a cycle in DataEdge dependencies
- **THEN** topological ordering fails with a validation error that identifies the participating node ids

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

### Requirement: DataEdge carries tensor semantics between nodes
DataEdge SHALL identify source node, target node, tensor name, and optional TensorSpec. DataEdge validation SHALL ensure referenced nodes exist and tensor names are consistent with node outputs/inputs when such lists are declared.

#### Scenario: Edge references missing node
- **WHEN** an edge references a source or target node id absent from the graph
- **THEN** ComputeGraph validation rejects the graph and reports the missing id

#### Scenario: Edge tensor is used for communication modeling
- **WHEN** an edge includes a TensorSpec with byte size
- **THEN** TaskGraph mapping and backend request generation use that byte size for data movement estimation

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
