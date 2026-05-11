# generic-workload-workflows Specification

## Purpose
Define the generic workload workflow contract that governs how workload families (ML/tensor, sparse linear algebra, stencil/streaming, graph analytics, database/vector-search, and custom) declare their workflow templates, coverage requirements, lowering policies, mapping seeds, simulation coverage, domain validation, evidence artifacts, and claim boundaries. This spec ensures the DSE pipeline remains generic and extensible without hardcoding domain-specific branches.
## Requirements
### Requirement: Workload families have explicit workflow templates
The system SHALL define workload-family workflow templates that describe accepted sources, adapter output, graph semantics, lowering policy, mapping seeds, simulation coverage, domain validation, evidence artifacts, and final claim boundary for each supported family. The templates SHALL be normative acceptance criteria for later adapter implementation and SHALL NOT be implemented as hardcoded branches in core DSE orchestration.

#### Scenario: Workflow template drives adapter implementation
- **WHEN** a developer implements an adapter for a supported family
- **THEN** the adapter declares the family workflow fields needed by the generic DSE pipeline rather than requiring new core schema fields

#### Scenario: Unknown family uses custom workflow declaration
- **WHEN** a user-defined scientific workload does not match a built-in family
- **THEN** it can still run by providing a custom workflow declaration with source kind, coverage, lowering, mapping, validation, and claim-boundary metadata

### Requirement: Adapter-required coverage replaces global QE phase checks
Each workload workflow SHALL declare required coverage as node ids, region ids, named phases, or executable-view tasks that must appear in timing evidence for a full-workload claim. DFT/QE SHALL use SCF phase coverage through the `dft_qe` adapter; non-QE workflows SHALL NOT be checked against QE phase names unless they explicitly declare them.

#### Scenario: Non-QE workload uses executable graph coverage
- **WHEN** an ML, sparse, stencil, graph analytics, database, or custom workload has no adapter-specific coverage list
- **THEN** the workflow uses the lowered executable graph nodes or regions as required coverage for full-flow evidence

#### Scenario: DFT/QE keeps SCF coverage
- **WHEN** the selected adapter is `dft_qe`
- **THEN** the workflow requires the canonical QE SCF coverage phases declared by the DFT/QE adapter and records them as adapter coverage, not as global core coverage

#### Scenario: Missing adapter coverage blocks trusted claims
- **WHEN** a required coverage item is absent from simulation events, summaries, or equivalent backend evidence
- **THEN** final trusted ranking, selected recommendation, and full-workload completion claims are blocked for that run

### Requirement: ML and tensor-graph workflow is defined
The ML/tensor workflow SHALL ingest tensor graphs such as ONNX-like graphs, framework-exported graphs, hand-authored tensor pipelines, or generic JSON tensor graphs. The adapter SHALL preserve model/operator provenance, tensor shapes, dtype/layout, batch or sequence dimensions, parameter/input sizes, precision policy, and optional accuracy/reference metadata. The workflow SHALL lower static DAGs directly, lower bounded dynamic axes through declared summaries, and mark unsupported dynamic control or unbounded shapes as non-final unless summarized.

#### Scenario: Static tensor graph runs as full workload
- **WHEN** an ML tensor graph declares all nodes, tensor specs, cost hints or model bindings, and full-workload coverage
- **THEN** mapping search and SystemC/gem5+SystemC simulation use generic op types and tensor sizes without requiring QE fields

#### Scenario: ML domain correctness is separate from timing
- **WHEN** the generic simulator reports latency, energy, utilization, and data movement for an ML workload
- **THEN** the final report labels those as timing/resource claims and requires adapter evidence for accuracy, numerical tolerance, or model-output equivalence claims

### Requirement: Sparse linear algebra workflow is defined
The sparse linear algebra workflow SHALL ingest CSR/CSC/COO/block-sparse or equivalent sparse operators, matrix/vector dimensions, sparsity metadata, index/value tensor specs, solver iteration summaries, and residual or reference-output requirements when correctness is claimed. The workflow SHALL represent SpMV, sparse triangular solve, preconditioner, gather/scatter, reduction, and solver-loop regions as generic nodes and declared loop/feedback regions.

#### Scenario: Sparse SpMV pipeline runs with sparse metadata
- **WHEN** a sparse workload emits SpMV, gather/scatter, and reduction nodes with sparse format metadata and tensor byte sizes
- **THEN** the generic DSE workflow can map and simulate the executable graph while preserving sparse format metadata for adapter reporting

#### Scenario: Sparse solver residual requires adapter validation
- **WHEN** a report claims solver convergence, residual quality, or numerical equivalence for a sparse workload
- **THEN** it cites adapter-owned residual or reference-output validation evidence in addition to generic timing evidence

### Requirement: Stencil streaming and signal-processing workflow is defined
The stencil/streaming workflow SHALL ingest structured-grid kernels, halo/dependency metadata, FFT/signal-processing stages, producer-consumer pipelines, tile shapes, time-step or iteration bounds, and streaming buffer requirements. The workflow SHALL model recurrence or stream feedback through declared `GraphRegion` or typed feedback/stream edges and SHALL lower them by unrolling, summary timing, or backend-native streaming representation before trusted simulation.

#### Scenario: Bounded stencil recurrence lowers to executable evidence
- **WHEN** a stencil workload declares time-step count, halo depth, tile shape, and streaming recurrence semantics
- **THEN** graph lowering records the summary or unroll policy and emits executable coverage items for simulation and report validation

#### Scenario: Unbounded stream is diagnostic only
- **WHEN** a streaming workload lacks bounds, convergence criteria, trace-derived trip counts, or a summary model
- **THEN** the workflow returns an unsupported or diagnostic result and prevents trusted final claims

### Requirement: Graph analytics workflow is defined
The graph analytics workflow SHALL ingest vertex/edge counts, graph format, frontier or traversal semantics, update/reduction operators, iteration or convergence bounds, and graph data movement metadata. Algorithms such as BFS, PageRank, connected components, SSSP, and graph neural message passing SHALL be represented as generic nodes and declared regions rather than core-special operators.

#### Scenario: Iterative graph analytics declares frontier semantics
- **WHEN** a graph analytics workload includes iterative frontier expansion or convergence loops
- **THEN** the adapter declares loop bounds, convergence summaries, or trace-derived iteration distributions for graph lowering

#### Scenario: Graph result quality is adapter-owned
- **WHEN** a report claims traversal result equivalence, ranking quality, or convergence for a graph workload
- **THEN** the claim cites adapter validation evidence rather than relying only on generic timing metrics

### Requirement: Database and vector-search workflow is defined
The database/vector-search workflow SHALL ingest query-plan or pipeline operators, data/index sizes, selectivity or cardinality estimates, memory hierarchy assumptions, scan/filter/join/aggregate/vector-search nodes, and query-result or recall/precision validation requirements. The workflow SHALL preserve query or index metadata as adapter-owned domain metadata while exposing generic compute, memory, and data-movement nodes to mapping and simulation.

#### Scenario: Vector-search pipeline maps generic operators
- **WHEN** a vector-search workload emits embedding lookup, distance computation, top-k, filter, and aggregation nodes
- **THEN** generic mapping search and simulation use their op types, tensor sizes, and memory movement without adding database-specific core fields

#### Scenario: Query correctness is not inferred from timing
- **WHEN** the simulator produces timing evidence for a database or vector-search workload
- **THEN** final correctness, recall, precision, or query-equivalence claims require adapter-owned validation artifacts

### Requirement: Dynamic-control and custom workflows are bounded before final simulation
Dynamic-control, recursive, data-dependent, stateful, or user-defined custom workflows SHALL declare enough semantics for graph lowering before they can satisfy trusted final evidence. Acceptable declarations include bounded loops, convergence criteria, trace-derived trip-count distributions, summary models, region-level reference behavior, or backend-native support.

#### Scenario: Unsupported dynamic control is blocked
- **WHEN** a custom workload contains recursion or data-dependent iteration with no bound, summary, trace distribution, or backend-native model
- **THEN** the workflow emits unsupported-graph diagnostics and blocks trusted full-workload simulation claims

#### Scenario: Custom workload can pass through generic JSON
- **WHEN** a user supplies a custom JSON graph with valid generic nodes, typed edges, tensor specs, cost hints, coverage, and claim boundary
- **THEN** the workflow can ingest, lower, map, simulate, and report it without adding a domain-specific adapter to core code

### Requirement: Workload-family final reports separate timing and domain claims
Final reports SHALL show for each workload family: adapter id/version, source provenance, claim boundary, required coverage, graph-lowering status, timing/resource evidence, unavailable metrics, adapter-domain validation status, and limitations. A trusted timing run SHALL NOT automatically imply domain correctness for any family.

#### Scenario: Timing-only evidence remains scoped
- **WHEN** a workload has passing SystemC or gem5+SystemC timing evidence but no adapter-domain validator
- **THEN** the report may make timing/resource feasibility claims but labels domain correctness unavailable or unclaimed

#### Scenario: Reduced diagnostic workload cannot satisfy final check
- **WHEN** a workload package is reduced, sampled, imported-trace-only, synthetic regression, smoke-only, or diagnostic-only
- **THEN** final validation prevents it from satisfying trusted full-workload completion or winner claims

### Requirement: Built-in non-QE workflows are acceptance paths
The built-in non-QE workflow families SHALL be treated as first-class acceptance paths for the workload analysis system, not as illustrative examples. At minimum, `ml_tensor`, `sparse_la`, `stencil_streaming`, `graph_analytics`, `database_vector_search`, and `dynamic_custom` SHALL declare accepted source kinds, graph pattern, lowering policy, default mapping policies, domain validation requirements, unavailable metrics, and claim boundary behavior.

#### Scenario: Workflow registry exposes broad families
- **WHEN** the workload workflow registry is serialized or inspected
- **THEN** it includes the built-in non-QE workload families with enough metadata for Step1, Step2, Step3, and reporting to avoid QE defaults

#### Scenario: Non-QE workflow coverage is derived generically
- **WHEN** a non-QE workflow does not declare an adapter-specific required coverage list
- **THEN** required coverage is derived from the lowered executable graph nodes or regions rather than from QE phase names

### Requirement: Adapter policies are namespaced
Adapter-provided mapping policies, validation artifacts, coverage labels, and domain metrics SHALL be namespaced by adapter id or workload family. Core workflow policy lists SHALL NOT promote one domain adapter's policies into global defaults.

#### Scenario: QE policy does not affect ML workload
- **WHEN** an ML/tensor workload is mapped
- **THEN** DFT/QE policy ids such as hardware diagonalization or operator sweep are not applied unless explicitly supplied by that workload's adapter metadata

