## ADDED Requirements

### Requirement: Simulation IPC uses versioned JSON schemas
The Python-to-C++ simulation interface SHALL use versioned JSON request and result schemas. The request schema SHALL include architecture, workload, mapping, scheduling, and output configuration; the result schema SHALL include metrics, events, resource utilization, uncertainty, and errors.

#### Scenario: Request schema identifies version
- **WHEN** GenericSystemCBackend writes a simulation request
- **THEN** the request includes a schema/version identifier compatible with `simulation_request_v1.json`

#### Scenario: Result schema identifies version
- **WHEN** `generic_sim` writes a result
- **THEN** the result includes a schema/version identifier or equivalent compatibility marker compatible with `simulation_result_v1.json`

### Requirement: Python bridge builds complete backend requests
GenericSystemCBackend SHALL translate DesignPoint and ComputeGraph inputs into a complete simulation request containing all accelerators, capabilities, memory/power fields, interconnect, workload nodes, workload edges, mapping, and scheduling policy needed by the C++ backend.

#### Scenario: Accelerator capabilities are emitted
- **WHEN** a design point contains GPU, FPGA, and CIM accelerators
- **THEN** the JSON request includes each accelerator id, type, operator capabilities, peak rates, memory, and power fields

#### Scenario: Workload edges are emitted
- **WHEN** the ComputeGraph contains dependencies between nodes
- **THEN** the JSON request includes those DataEdges with tensor names and sizes for backend ordering and transfer modeling

### Requirement: C++ parser consumes architecture, workload, mapping, and capabilities
The C++ JsonParser SHALL parse accelerator descriptors, operator capabilities, power fields, interconnect fields, workload nodes, workload edges, tensor shapes, mapping, and scheduling fields from the request. Missing optional fields SHALL use documented defaults; missing required fields SHALL produce parse errors.

#### Scenario: Parser reads accelerator capability differences
- **WHEN** a request defines different GEMM capabilities for GPU and CIM accelerators
- **THEN** the parsed SimulationRequest preserves those differences for GraphExecutor

#### Scenario: Parser rejects malformed required field
- **WHEN** a required numeric field such as peak capability is malformed
- **THEN** parsing fails with a structured error rather than substituting zero silently

### Requirement: Operator model registry is extensible and deterministic
The backend SHALL provide an operator model registry that maps op types to cost models. Built-in models SHALL include at least GEMM, FFT, eigen, reduction, elementwise or generic operation support, and transfer modeling. Unknown op types SHALL resolve to a declared generic model only when explicitly allowed.

#### Scenario: Known operator uses specialized model
- **WHEN** GraphExecutor evaluates a `gemm` node
- **THEN** it uses the GEMM model rather than the generic fallback

#### Scenario: Unknown operator fallback is labeled
- **WHEN** an unknown operator is evaluated through GenericOpModel
- **THEN** the result provenance labels that fallback so accuracy claims are downgraded

### Requirement: GraphExecutor respects dependencies and data movement
GraphExecutor SHALL execute workload nodes in topological order, respect DataEdge dependencies, apply mapping to accelerator ids, and estimate transfers when producer and consumer nodes are placed on different devices.

#### Scenario: Dependent consumer waits for producer
- **WHEN** node B depends on node A through a DataEdge
- **THEN** backend execution schedules B no earlier than A completion plus required transfer time

#### Scenario: Cross-device edge adds transfer event
- **WHEN** a producer and consumer are mapped to different accelerators
- **THEN** the result includes a data-transfer contribution and trace event or equivalent diagnostic

### Requirement: Backend results include metrics, trace, utilization, and uncertainty
SimulationResult SHALL include latency, throughput, power, energy, data movement, trace events, resource utilization, and uncertainty/confidence fields where available. Missing unavailable fields SHALL be explicit rather than defaulting to misleading zeros.

#### Scenario: Successful run returns auditable trace
- **WHEN** generic_sim completes a valid request
- **THEN** the result contains enough events and utilization data to explain the reported latency and bottlenecks

#### Scenario: Unavailable metric is marked unavailable
- **WHEN** the backend cannot estimate area or calibrated power
- **THEN** the metric is marked unavailable or low-confidence rather than presented as a measured zero

### Requirement: Backend errors do not masquerade as successful results
GenericSystemCBackend and generic_sim SHALL distinguish parse errors, executable errors, timeout errors, validation errors, and infeasible architecture errors. Failed backend invocation SHALL not be ranked as a feasible design point.

#### Scenario: Executable missing is an evaluation error
- **WHEN** the configured generic_sim executable is missing
- **THEN** the bridge returns an infeasible/error result with diagnostic text and does not report successful latency

#### Scenario: Timeout is recoverable at DSE level
- **WHEN** a backend invocation times out
- **THEN** the DSE run records the failed design point and continues evaluating independent candidates if configured

### Requirement: Backend supports architecture-difference regression probes
The generic backend SHALL include regression tests or probes that confirm different accelerator descriptors, mappings, and interconnects affect output metrics in expected directions.

#### Scenario: Capability scaling changes latency
- **WHEN** the same GEMM workload is evaluated with peak compute doubled and all else equal
- **THEN** compute-bound latency decreases or provenance explains why it is bounded by another resource

#### Scenario: Mapping changes communication
- **WHEN** a two-node workload is mapped to one accelerator versus two accelerators with cross-device transfer
- **THEN** total data movement or communication overhead differs according to the mapping

### Requirement: gem5 GenericAccel status boundary is explicit
The gem5 GenericAccel model SHALL be specified as an MMIO timed stub until DMA descriptor reading, command queue semantics, TLM/SystemC bridge, interrupt/completion behavior, and result writeback are implemented and validated.

#### Scenario: Stub mode command completes with fixed timing
- **WHEN** GenericAccel operates in timed-stub mode and receives a command doorbell
- **THEN** it may complete using fixed or parameterized timing, and the result is labeled stub timing

#### Scenario: Full L4 mode requires descriptor path
- **WHEN** a report claims full L4 gem5 + SystemC co-simulation
- **THEN** evidence shows descriptor/request ingestion, backend execution, result delivery, and guest-visible completion

### Requirement: Build, regression, and full-flow pilot commands are reproducible
The backend SHALL document and support reproducible build/regression commands for C++ generic_sim, standalone SystemC timing-level QE-flow pilots, and gem5+SystemC QE-flow validation when the L4 binding is available. Smoke checks MAY exist only as bring-up diagnostics and SHALL NOT be treated as DSE completion evidence.

#### Scenario: C++ backend build is verified
- **WHEN** implementation claims the standalone backend is usable
- **THEN** `cmake --build model/generic_sim_backend/build -j4` or equivalent succeeds and is recorded

#### Scenario: Standalone SystemC full-flow pilot is verified before trusted L3 claims
- **WHEN** implementation claims standalone SystemC timing-level evidence is usable for DSE
- **THEN** a SystemC pilot runs a full QE SCF shell workload, exports the required evidence artifacts, and labels gem5+SystemC as blocked/prototype unless the L4 descriptor/completion path also ran

#### Scenario: gem5 plus SystemC full-flow pilot is verified before L4 claims
- **WHEN** implementation claims L4 integration is usable for DSE
- **THEN** a gem5+SystemC pilot runs a QE-flow workload through command submission, SystemC timing execution, completion, and evidence export
