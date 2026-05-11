## ADDED Requirements

### Requirement: Accelerator self-description covers four capability domains
Each Accelerator SHALL self-describe compute, memory, communication, and power capabilities. The descriptor SHALL be sufficient for generic evaluators to decide operator support, estimate latency/energy, and check resource feasibility without type-specific hardcoding.

#### Scenario: Accelerator descriptor is complete
- **WHEN** an accelerator is added to a SystemArchitecture
- **THEN** it declares compute capabilities, memory hierarchy, communication links, and power model fields required by the schema

#### Scenario: Incomplete descriptor is rejected
- **WHEN** an accelerator lacks a required capability domain
- **THEN** architecture validation rejects it or marks it unavailable for evaluation with a structured reason

### Requirement: Compute capabilities are precision-aware and operator-aware
ComputeCapability SHALL express peak compute by precision and operator efficiency by operator type. Evaluators SHALL use the requested precision and operator efficiency when estimating latency.

#### Scenario: Precision-specific peak is selected
- **WHEN** a FP64 GEMM task is mapped to an accelerator with both FP64 and FP32 peaks
- **THEN** the evaluator uses the FP64 peak and the GEMM efficiency for that accelerator

#### Scenario: Unsupported operator is infeasible
- **WHEN** a task is mapped to an accelerator whose supported operator list excludes the task `op_type`
- **THEN** the design point is marked infeasible with an unsupported-operator violation

### Requirement: Memory hierarchy models capacity, bandwidth, latency, and kind
MemoryHierarchy SHALL model each memory level with name, capacity bytes, bandwidth GB/s or Gbps as specified by the schema, latency, and memory kind. Evaluators SHALL check capacity and bandwidth constraints before accepting a placement.

#### Scenario: Working set exceeds local memory
- **WHEN** a task placement requires more bytes than the selected local memory level can hold
- **THEN** the evaluator reports a memory-capacity violation or inserts an explicit spill policy if configured

#### Scenario: Memory bandwidth limits latency
- **WHEN** operational intensity indicates a task is memory-bound
- **THEN** analytical evaluation uses the selected memory bandwidth to bound achievable throughput

### Requirement: Communication capability distinguishes host links and peer links
CommunicationCapability SHALL distinguish host links, peer links, and collective/streaming primitives. Data movement cost SHALL be derived from the most specific valid route between source and destination.

#### Scenario: Peer link overrides default interconnect
- **WHEN** two accelerators have a declared peer link with higher bandwidth than the system default interconnect
- **THEN** communication modeling uses the peer link for transfers between those accelerators

#### Scenario: Missing route is infeasible or uses declared fallback
- **WHEN** a task mapping requires data movement between devices with no host, peer, or interconnect route
- **THEN** the design point is infeasible unless a fallback staging route is explicitly declared

### Requirement: SystemArchitecture composes host, accelerators, interconnect, and budgets
SystemArchitecture SHALL represent the host, accelerator set, interconnect topology, power budget, area budget, and optional cost constraints. It SHALL provide lookup and aggregate-capacity methods used consistently by DSE evaluators.

#### Scenario: Duplicate accelerator id is rejected
- **WHEN** two accelerators in one system share the same `accel_id`
- **THEN** architecture validation rejects the system before generating design points

#### Scenario: Aggregate power exceeds budget
- **WHEN** estimated static plus dynamic power exceeds `max_power_w`
- **THEN** the EvaluationResult marks the design point infeasible or reports a budget violation in ranked outputs

### Requirement: Accelerator templates are reference presets, not hidden assumptions
Built-in templates such as GPU A100, FPGA U280, and CIM Array SHALL be documented as reference presets. The generic framework SHALL support user-defined accelerators with equivalent capability fields.

#### Scenario: Custom accelerator is accepted
- **WHEN** a user supplies a custom accelerator descriptor with valid compute, memory, communication, and power fields
- **THEN** DSE can include it without code changes to evaluator type dispatch

#### Scenario: Template values are traceable
- **WHEN** a built-in accelerator template is used in a report
- **THEN** the report identifies the template name/version and any parameter overrides

### Requirement: Power and energy modeling is explicit and auditable
PowerModel SHALL distinguish static power, compute dynamic power, memory dynamic power, and communication dynamic power where available. Energy SHALL be computed from power and elapsed time using explicit units.

#### Scenario: Energy is derived from latency and power
- **WHEN** an EvaluationResult reports latency in milliseconds and power in watts
- **THEN** energy in joules is computed as `power_w * latency_ms / 1000` unless a more detailed timeline integration is declared

#### Scenario: Missing power model is not reported as measured power
- **WHEN** an accelerator lacks a calibrated power model
- **THEN** reports label power/energy as estimated, unknown, or unavailable rather than measured

### Requirement: Distributed systems model nodes, network links, and failure domains
DistributedSystem SHALL model node-local SystemArchitecture objects, inter-node NetworkLinks, rack/cluster/failure-domain metadata, and communication costs. Single-node systems SHALL be representable as a degenerate distributed system.

#### Scenario: Inter-node transfer cost is computed
- **WHEN** data moves between tasks placed on accelerators in different nodes
- **THEN** transfer time uses the declared NetworkLink bandwidth and latency plus any local staging costs

#### Scenario: Failure domain is preserved
- **WHEN** a distributed design point is serialized for analysis
- **THEN** node failure-domain metadata is preserved for resilience or placement constraints

### Requirement: Architecture validation produces feasibility reasons
Architecture validation SHALL produce machine-readable feasibility reasons for unsupported operators, missing links, budget violations, memory capacity violations, invalid units, and duplicate identifiers.

#### Scenario: Multiple architecture violations are surfaced
- **WHEN** a design point violates both power budget and operator support
- **THEN** EvaluationResult includes both violation reasons rather than only the first failure

#### Scenario: Reports separate invalid from suboptimal designs
- **WHEN** a design point is infeasible
- **THEN** it is excluded from Pareto-optimal candidates but retained in diagnostics with violation reasons
