## ADDED Requirements

### Requirement: DFT/QE adapter maps SCF workflow to generic ComputeGraph
The DFT/QE workload adapter SHALL express the QE SCF workflow as a generic ComputeGraph using standard ComputeNode, DataEdge, TensorSpec, and attributes without adding QE-specific requirements to the core IR.

#### Scenario: SCF graph uses generic node contract
- **WHEN** the adapter builds the canonical QE SCF graph
- **THEN** each operation is represented as a ComputeNode with generic `op_type`, tensor specs, cost estimates, and DFT metadata in attributes

#### Scenario: Core IR remains domain-neutral
- **WHEN** a non-DFT workload is represented in ComputeGraph
- **THEN** it does not need QE fields or DFT-specific classes to pass core IR validation

### Requirement: Canonical QE SCF graph includes the expected operation chain
The adapter SHALL provide a canonical SCF reference graph covering Hamiltonian application, overlap-operator application, nonlocal potential, preconditioning, orthogonalization, reduced matrix builds, generalized diagonalization, subspace rotation, refresh, residual/convergence update, density output, density mixing, and effective potential update.

#### Scenario: Canonical graph contains full shell reference operations
- **WHEN** the default QE SCF graph is generated
- **THEN** it contains nodes corresponding to `h_psi`, `s_psi`, `vnl`, `precondition`, `orthogonalize`, `build_H_sub`, `build_S_sub`, `diagonalize`, `subspace_rotation`, `refresh`, `residual`, `rho_out`, `mix_rho`, and `veff`

#### Scenario: Operation order preserves dependencies
- **WHEN** the SCF graph is topologically sorted
- **THEN** diagonalization occurs after reduced H/S build dependencies and before subspace rotation/refresh dependencies

### Requirement: DFT tensor and workload parameters are explicit
The adapter SHALL parameterize DFT workloads with explicit values for `npw`, `nkb`, number of bands, FFT grid size, precision, spin/k-point metadata where applicable, and derived tensor shapes/byte sizes.

#### Scenario: Parameter override changes tensor shape
- **WHEN** a user changes `npw` or band count for a QE workload
- **THEN** affected TensorSpecs and estimated FLOPs/memory bytes are recomputed consistently

#### Scenario: Precision is not implicit
- **WHEN** a DFT workload uses complex FP64 data
- **THEN** tensor dtype and byte-size logic explicitly account for complex-valued storage rather than assuming scalar FP64

### Requirement: Trace ingestion preserves provenance and units
When QE traces or dump-derived measurements are used, the adapter SHALL preserve source path, generation command where available, timestamp or dataset id, units, and mapping from trace events to ComputeGraph nodes.

#### Scenario: Trace row maps to node id
- **WHEN** a QE trace row is ingested for `h_psi` timing or FLOPs
- **THEN** the adapter records which ComputeNode attribute or calibration field consumed that row

#### Scenario: Missing provenance downgrades confidence
- **WHEN** trace-derived data lacks source path or units
- **THEN** the adapter marks calibration confidence lower and reports the missing provenance in validation output

### Requirement: DFT adapter supports reference and reduced workloads
The adapter SHALL support a full SCF reference graph and smaller synthetic/reduced workloads used for fast validation, provided each reduced workload labels what was omitted or approximated.

#### Scenario: Reduced workload is labeled non-final
- **WHEN** a reduced GEMM/eigen workload is generated for backend bring-up or regression
- **THEN** it is labeled reduced/non-final and not reported as full QE SCF coverage

#### Scenario: Full SCF graph remains available
- **WHEN** a DSE run requests the canonical DFT workload
- **THEN** the adapter can produce the full SCF graph with all reference operation nodes

### Requirement: DFT mapping policies are configurable
The adapter SHALL support configurable mapping policies such as host-only baseline, FPGA operator sweep, hardware diagonalization, all-operator offload, streaming, batch, and fallback placements. Policies SHALL produce explicit DesignPoint mappings.

#### Scenario: Hardware diagonalization policy maps eigen node
- **WHEN** a hardware-diagonalization policy is selected
- **THEN** the `diagonalize` node maps to the configured accelerator and the mapping is visible in the DesignPoint

#### Scenario: Unsupported policy is rejected
- **WHEN** a requested mapping policy is unknown or incompatible with the architecture
- **THEN** adapter validation fails with a policy error rather than generating a partial mapping silently

### Requirement: DFT metrics include domain and framework views
DFT evaluation reports SHALL include framework metrics such as latency, throughput, power, energy, utilization, and data movement, plus DFT-domain metrics such as SCF iteration latency, subspace diagonalization latency, operator-sweep share, and residual/refresh share where available.

#### Scenario: Report includes phase-family timing shares
- **WHEN** a QE architecture configuration is evaluated
- **THEN** the report can show operator application, reduced build, diagonalization, refresh/residual, and density/mixing/update shares using available model or trace evidence without assuming a fixed cluster template

#### Scenario: Missing domain metric is declared
- **WHEN** a DFT-domain metric cannot be computed from the workload or backend result
- **THEN** the report marks it unavailable rather than filling a misleading default

### Requirement: Calibration compares model output against QE evidence
The adapter SHALL support calibration checks between DSE model outputs and QE trace/baseline evidence. Calibration results SHALL include absolute error, relative error, dataset id, and confidence notes.

#### Scenario: Calibration computes relative error
- **WHEN** model latency and QE trace latency are both available for a node or phase
- **THEN** calibration reports absolute and relative error with denominator guards for near-zero values

#### Scenario: Calibration failure blocks strong claims
- **WHEN** calibration error exceeds the configured tolerance
- **THEN** reports do not claim high-confidence model accuracy for that workload family

### Requirement: DFT adapter respects algorithm-freeze priorities
The adapter SHALL preserve current project priorities around generalized Hermitian eigensolver, Ozaki/CRT design decisions, and avoiding unnecessary QE dataset rebuilds. DSE documentation SHALL not require regenerating traces unless a task explicitly needs new evidence.

#### Scenario: Existing trace is reused
- **WHEN** existing validated trace/dump data satisfies a calibration need
- **THEN** the workflow reuses it and records the dataset path instead of rebuilding QE from scratch

#### Scenario: New QE run is explicitly justified
- **WHEN** a validation gap requires a new QE run or trace rebuild
- **THEN** the task records why existing evidence is insufficient and which workspace copy is safe to touch

### Requirement: DFT regression suite covers generic and domain-specific behavior
The DFT adapter SHALL include regression tests that verify graph construction, parameterization, mapping policy output, generic backend compatibility, and key DFT-domain metrics.

#### Scenario: Graph construction regression passes
- **WHEN** the adapter test builds the canonical QE SCF graph
- **THEN** validation confirms required nodes, edges, tensor specs, and metadata are present

#### Scenario: Backend compatibility regression passes
- **WHEN** the DFT graph is sent through a generic evaluator or backend bridge
- **THEN** the path succeeds or returns a structured unsupported-feature error without QE-specific crashes
