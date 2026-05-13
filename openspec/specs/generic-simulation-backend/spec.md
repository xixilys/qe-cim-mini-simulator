# generic-simulation-backend Specification

## Purpose
Define the generic simulation backend contract for a **truly heterogeneous architecture** (Host + GPU/FPGA/CIM/ASIC/custom accelerators). This spec covers JSON IPC, Python bridge semantics, C++/SystemC parsing and execution, architecture-difference probes, result/error semantics, evidence artifacts, and the explicit gem5 GenericAccel diagnostic/untrusted versus trusted L4 boundary.

## Architecture Transition
The backend SHALL support a **configurable heterogeneous architecture** where accelerators are dynamically specified in the simulation request (e.g., `gpu-0`, `fpga-0`, `cim-0`), rather than hardcoded to a historical fixed application pipeline. Legacy fixed-pipeline models are removed from active simulator modes and may be restored only as explicit data-only reference artifacts.
## Requirements
### Requirement: Simulation IPC uses versioned JSON schemas
The Python-to-C++ simulation interface SHALL use versioned JSON request and result schemas. The request schema SHALL include architecture, workload, mapping, scheduling, and output configuration; the result schema SHALL include metrics, events, resource utilization, uncertainty, and errors.

#### Scenario: Request schema identifies version
- **WHEN** GenericSystemCBackend writes a simulation request
- **THEN** the request includes a schema/version identifier compatible with `simulation_request_v1.json`

#### Scenario: Result schema identifies version
- **WHEN** `generic_sim` writes a result
- **THEN** the result includes a schema/version identifier or equivalent compatibility marker compatible with `simulation_result_v1.json`

### Requirement: Python bridge builds complete backend requests for heterogeneous architectures
GenericSystemCBackend SHALL translate DesignPoint and ComputeGraph inputs into a complete simulation request containing **dynamically configured accelerators** (not hardcoded clusters), capabilities, memory/power fields, interconnect, workload nodes, workload edges, mapping, and scheduling policy needed by the C++ backend.

#### Scenario: Accelerator capabilities are emitted for heterogeneous system
- **WHEN** a design point contains GPU, FPGA, and CIM accelerators with ids `gpu-0`, `fpga-0`, `cim-0`
- **THEN** the JSON request includes each accelerator id, type, operator capabilities, peak rates, memory, and power fields
- **AND** the backend executes them as independent devices, not as fixed application-pipeline roles

#### Scenario: Historical fixed-pipeline mode is rejected from the active backend
- **WHEN** the request includes a legacy fixed-pipeline mode or architecture family
- **THEN** the backend rejects it as unsupported by the active generic simulator contract
- **AND** the runbook points the user to legacy reference storage if they need to inspect historical artifacts

#### Scenario: Heterogeneous architecture reflects explicit capabilities
- **WHEN** the same workload is evaluated with different heterogeneous architecture descriptors
- **THEN** the results show different latency, power, and data movement patterns reflecting the explicit accelerator capabilities and interconnect topology

#### Scenario: Workload edges are emitted
- **WHEN** the ComputeGraph contains dependencies between nodes
- **THEN** the JSON request includes those DataEdges with tensor names and sizes for backend ordering and transfer modeling

#### Scenario: Lowered executable graph is emitted for non-DAG workloads
- **WHEN** the source ComputeGraph contains loops, streaming feedback, control-flow regions, hierarchy, or stateful dependencies
- **THEN** the bridge emits the lowered executable graph, loop summary, or backend-supported streaming representation plus source-graph correspondence and lowering provenance

### Requirement: C++ parser consumes architecture, workload, mapping, and capabilities
The C++ JsonParser SHALL parse accelerator descriptors, operator capabilities, power fields, interconnect fields, workload nodes, workload edges, tensor shapes, mapping, and scheduling fields from the request. Missing optional fields SHALL use documented defaults; missing required fields SHALL produce parse errors.

#### Scenario: Parser reads accelerator capability differences
- **WHEN** a request defines different GEMM capabilities for GPU and CIM accelerators
- **THEN** the parsed SimulationRequest preserves those differences for GraphExecutor

#### Scenario: Parser rejects malformed required field
- **WHEN** a required numeric field such as peak capability is malformed
- **THEN** parsing fails with a structured error rather than substituting zero silently

#### Scenario: Parser rejects missing required field
- **WHEN** a required field such as `schema_version`, `architecture`, or `workload` is absent from the request
- **THEN** parsing fails with `missing_required_field` error and does not proceed to execution

#### Scenario: Parser rejects invalid schema version
- **WHEN** the request `schema_version` is unknown or incompatible with the backend
- **THEN** parsing fails with `schema_version_incompatible` error listing supported versions

#### Scenario: Parser rejects malformed numeric values
- **WHEN** a numeric field contains a string, null, or non-numeric value
- **THEN** parsing fails with `malformed_numeric` error and does not substitute zero or default values

### Requirement: Backend request carries complete tensor metadata
The Python bridge SHALL include complete tensor metadata in the simulation request, including `size_bytes`, `dtype`, and `element_size`. The C++ backend SHALL use this metadata for accurate data movement and timing calculations.

#### Scenario: Request includes tensor size_bytes
- **WHEN** a DataEdge includes a TensorSpec with `size_bytes=524288` (FP32, shape [1024, 128])
- **THEN** the simulation request includes `size_bytes=524288` and the backend uses this value for transfer time calculation

#### Scenario: Request includes dtype for byte size verification
- **WHEN** a TensorSpec has `dtype="FP32"` and `shape=[1024, 128]`
- **THEN** the request includes both `dtype="FP32"` and `size_bytes=524288`; if `size_bytes` is inconsistent with `dtype` and `shape`, validation reports a mismatch error

#### Scenario: FP32 edge produces different data movement than FP64
- **WHEN** the same workload is evaluated with FP32 tensors versus FP64 tensors
- **THEN** the simulation result shows different `total_data_movement_mb` and transfer timing proportional to the dtype byte width

#### Scenario: INT8 edge produces smaller data movement
- **WHEN** a workload uses INT8 quantization with `dtype="INT8"`
- **THEN** the data movement is 1/8 of the equivalent FP64 tensor and 1/4 of the equivalent FP32 tensor

### Requirement: Operator model registry is extensible and deterministic
The backend SHALL provide an operator model registry that maps op types to cost models. Built-in models SHALL include at least GEMM, FFT, eigen, reduction, elementwise or generic operation support, and transfer modeling. Unknown op types SHALL resolve to a declared generic model only when explicitly allowed.

#### Scenario: Known operator uses specialized model
- **WHEN** GraphExecutor evaluates a `gemm` node
- **THEN** it uses the GEMM model rather than the generic fallback

#### Scenario: Unknown operator fallback is labeled
- **WHEN** an unknown operator is evaluated through GenericOpModel
- **THEN** the result provenance labels that fallback so accuracy claims are downgraded

### Requirement: GraphExecutor respects dependencies, executable regions, and data movement
GraphExecutor SHALL execute the lowered workload view in a valid dependency/region order, respect DataEdge and declared control/state dependencies, apply mapping to accelerator ids, and estimate transfers when producer and consumer nodes are placed on different devices.

#### Scenario: Dependent consumer waits for producer
- **WHEN** node B depends on node A through a DataEdge
- **THEN** backend execution schedules B no earlier than A completion plus required transfer time

#### Scenario: Cross-device edge adds transfer event
- **WHEN** a producer and consumer are mapped to different accelerators
- **THEN** the result includes a data-transfer contribution and trace event or equivalent diagnostic

#### Scenario: Unsupported graph construct fails explicitly
- **WHEN** a backend receives a loop, dynamic-control region, stateful dependency, or streaming construct that has not been lowered or is not supported natively by the binding
- **THEN** the backend returns a structured unsupported-graph error and the sample remains diagnostic rather than trusted final evidence

### Requirement: Microarchitecture simulators are opt-in per accelerator descriptor
The standalone backend SHALL use typed microarchitecture simulators for FPGA, CIM, GPU, and ASIC only when the accelerator descriptor carries concrete microarchitecture parameters. A legacy or v1-style accelerator descriptor with capabilities but no microarchitecture block SHALL continue to use the operator capability model so existing evidence and reference timing remain replayable.

#### Scenario: Configured microarchitecture uses typed simulator
- **WHEN** an accelerator descriptor includes concrete FPGA systolic-array, CIM crossbar, GPU SM, or ASIC pipeline fields
- **THEN** GraphExecutor dispatches the mapped node to the matching microarchitecture simulator and records timing derived from that simulator

#### Scenario: Capability-only descriptor keeps operator-model fallback
- **WHEN** an accelerator descriptor only includes operator capabilities and lacks concrete microarchitecture parameters
- **THEN** GraphExecutor uses the operator model fallback rather than silently changing timing by accelerator type alone

#### Scenario: Simulator transfer timing respects dtype width
- **WHEN** otherwise identical transfer edges use FP64, FP32, FP16/BF16, or INT8 tensors
- **THEN** simulator transfer cycles scale according to the tensor dtype byte width and shape

#### Scenario: Microarchitecture regression covers all supported accelerator types
- **WHEN** backend regression tests are run
- **THEN** FPGA, CIM, GPU, and ASIC simulator factory creation, finite compute timing, finite power estimates, and dtype-sensitive transfer timing are checked

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

### Requirement: Backend supports architecture-difference regression probes for heterogeneous systems
The generic backend SHALL include regression tests or probes that confirm different accelerator descriptors, mappings, and interconnects affect output metrics in expected directions. The backend SHALL specifically test heterogeneous configurations (e.g., GPU+FPGA+CIM) against homogeneous baselines.

#### Scenario: Heterogeneous vs homogeneous performance
- **WHEN** the same workload is evaluated on a heterogeneous system (Host+GPU+FPGA+CIM) versus a homogeneous system (Host-only or GPU-only)
- **THEN** the heterogeneous system shows different latency, power, and data movement patterns reflecting the actual accelerator mix

#### Scenario: Capability scaling changes latency
- **WHEN** the same GEMM workload is evaluated with peak compute doubled and all else equal
- **THEN** compute-bound latency decreases or provenance explains why it is bounded by another resource

#### Scenario: Mapping changes communication
- **WHEN** a two-node workload is mapped to one accelerator versus two accelerators with cross-device transfer
- **THEN** total data movement or communication overhead differs according to the mapping

### Requirement: gem5 GenericAccel L4 trust boundary is explicit
The gem5 GenericAccel path SHALL be trusted only when a real gem5-driven run validates descriptor/request ingestion, SystemC backend submission, completion/result writeback, guest-visible success, and result status. The workflow SHALL NOT synthesize diagnostic evidence for missing L4 runs.

#### Scenario: Missing real L4 flag fails explicitly
- **WHEN** a user requests the gem5+SystemC backend without enabling the real L4 harness
- **THEN** the command fails with an explicit error instead of generating synthetic diagnostic artifacts

#### Scenario: Full L4 mode requires descriptor path
- **WHEN** a report claims full L4 gem5 + SystemC co-simulation
- **THEN** evidence shows descriptor/request ingestion, backend execution, result delivery, and guest-visible completion

#### Scenario: Legacy compatibility target is not sufficient for generic L4 closure
- **WHEN** a legacy application-specific TLM/MMIO compatibility target completes through a historical fixed-purpose device path
- **THEN** the result MAY be cited as local TLM/MMIO compatibility evidence
- **AND** it SHALL NOT be cited as generic heterogeneous L4 closure unless the GSIM descriptor/request/completion proof also passes

### Requirement: Build, regression, and full-flow pilot commands are reproducible for heterogeneous architectures
The backend SHALL document and support reproducible build/regression commands for C++ generic_sim with **heterogeneous accelerator support**, standalone SystemC timing-level full-workload pilots, and gem5+SystemC validation when the L4 binding is available. The build system SHALL compile the generic heterogeneous backend by default; historical fixed-pipeline models SHALL remain outside the default active build. Smoke checks MAY exist only as bring-up diagnostics and SHALL NOT be treated as DSE completion evidence. A final trusted check SHALL require a complete SystemC or gem5+SystemC full-flow simulation for the selected WorkloadPackage; smoke-only, fixed-timing bring-up, legacy smoke conversion or diagnostic replay paths SHALL fail final trusted validation even when their commands exit successfully.

#### Scenario: C++ heterogeneous backend build is verified
- **WHEN** implementation claims the standalone backend is usable
- **THEN** `cmake --build model/generic_sim_backend/build -j4` or equivalent succeeds and produces a `generic_sim` executable that supports heterogeneous accelerator configurations
- **AND** the build does NOT default to a historical fixed-pipeline model

#### Scenario: Standalone SystemC full-flow pilot is verified before trusted L3 claims
- **WHEN** implementation claims standalone SystemC timing-level evidence is usable for DSE
- **THEN** a SystemC pilot runs the selected full WorkloadPackage, exports the required evidence artifacts, and records gem5+SystemC as `not_run` unless the L4 descriptor/completion path also ran

#### Scenario: gem5 plus SystemC full-flow pilot is verified before L4 claims
- **WHEN** implementation claims L4 integration is usable for DSE
- **THEN** a gem5+SystemC pilot runs the selected full WorkloadPackage through command submission, SystemC timing execution, completion, and evidence export

#### Scenario: Reference workload uses heterogeneous backend, not a historical fixed pipeline
- **WHEN** a reference workload profile/importer is selected and the architecture is a heterogeneous system (e.g., Host+FPGA+CIM)
- **THEN** the generic backend consumes its emitted ComputeGraph through the same heterogeneous request schema used for other workload families
- **AND** workload-specific node names remain profile/importer metadata instead of fixed backend roles

#### Scenario: Smoke-only evidence fails final validation
- **WHEN** a report, candidate, or run attempts to use smoke output as completion evidence
- **THEN** final validation rejects the trusted claim unless full-flow SystemC evidence or passing `gem5_l4_proof.json` evidence is present

### Requirement: gem5 plus SystemC trust requires an explicit L4 proof artifact
A gem5+SystemC sample SHALL enter trusted L4 evidence only when `gem5_l4_proof.json` exists and passes. The proof SHALL check descriptor or request ingestion, SystemC backend submission, completion/result writeback, guest-visible success, and passed SystemC result status.

#### Scenario: Passing L4 proof enables trusted gem5 sample
- **WHEN** a gem5+SystemC run records descriptor/request ingestion, SystemC submission, completion writeback, guest-visible success, and a passed SystemC result
- **THEN** `gem5_l4_proof.json` passes and the sample may be eligible for trusted L4 transport/timing claims

#### Scenario: Missing L4 proof blocks L4 trust
- **WHEN** a gem5+SystemC run lacks descriptor ingestion, backend submission, result writeback, guest-visible completion, or passed result evidence
- **THEN** the run is labeled untrusted for L4 and does not enter trusted final ranking as gem5+SystemC evidence

### Requirement: L4 proof states its numerical and physical claim boundary
The backend evidence SHALL state that L4 proof covers gem5 descriptor/request/SystemC/completion transport plus generic timing-result replay. It SHALL NOT claim QE FP64 residual, density, eigenvector, physical SCF convergence, or board/ASIC correctness unless separate domain evidence exists.

#### Scenario: L4 report avoids QE physics overclaim
- **WHEN** a final report cites a passing `gem5_l4_proof.json`
- **THEN** the report states the transport/timing claim boundary and keeps QE FP64 physics correctness outside the trusted claim

#### Scenario: Numerical validation remains separately cited
- **WHEN** a gem5+SystemC sample is trusted for L4 transport/timing
- **THEN** the report also cites `numerical_validation.json` for generic timing numeric checks and labels the validation scope explicitly

### Requirement: Backend sample records preserve proof status and unavailable reasons
Simulation sample records SHALL include backend-specific proof status. For gem5+SystemC, the sample SHALL reference `gem5_l4_proof.json`; for standalone SystemC, the sample SHALL state that L4 proof is not applicable rather than treating it as a missing failure.

#### Scenario: Standalone SystemC sample is not penalized for missing L4 proof
- **WHEN** a standalone SystemC sample passes phase coverage and numerical validation
- **THEN** it may be trusted as L3 SystemC evidence while recording that L4 proof is not applicable

#### Scenario: gem5 proof path is visible in sample evidence
- **WHEN** a gem5+SystemC sample is recorded in `mapping_simulation_samples.json`
- **THEN** its evidence ids include `gem5_l4_proof.json` or its missing-proof reason is listed in the sample record

### Requirement: Generic backend L4 proof is derived from real descriptor/request closure
The generic simulation backend integration SHALL mark gem5+SystemC evidence as trusted L4 only when the real gem5 path submits a descriptor or equivalent request to the SystemC backend and observes completion/result writeback through the guest-visible path.

#### Scenario: GenericAccel descriptor path drives SystemC request
- **WHEN** `Gem5SystemCClosureProfile/importer` runs the real L4 harness
- **THEN** the generated proof records gem5 descriptor/request ingestion and SystemC backend submission for the selected generic heterogeneous workload
- **AND** standalone TLM/MMIO compatibility output alone is not accepted as generic L4 closure

#### Scenario: SystemC status is included in L4 proof
- **WHEN** the SystemC backend returns a failed or malformed result during a real L4 run
- **THEN** the L4 proof fails and records the SystemC result status as the blocker
