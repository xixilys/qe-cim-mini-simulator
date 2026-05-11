## ADDED Requirements

### Requirement: Broad workload analysis is the top-level workload stage
The system SHALL define the workload stage as a broad workload analysis system for AI/tensor graphs, scientific computing, sparse linear algebra, stencil/streaming, graph analytics, database/vector search, DFT/QE, and custom computations. The stage SHALL normalize every supported workload into domain-neutral artifacts before mapping, simulation, or DSE.

#### Scenario: Non-QE workload is first-class
- **WHEN** a user submits an ML/tensor, sparse, stencil, graph analytics, database/vector-search, or custom workload through a supported adapter or generic JSON graph
- **THEN** the workload stage emits a valid `WorkloadPackage`, `ComputeGraph`, workflow metadata, claim boundary, and required coverage without requiring QE fields

#### Scenario: QE is a reference adapter
- **WHEN** a user submits a DFT/QE workload
- **THEN** the system treats QE-specific phases, node names, and correctness labels as `dft_qe` adapter metadata rather than global workload-stage requirements

### Requirement: Workload analysis emits reusable downstream artifacts
The broad workload analysis stage SHALL emit artifacts that downstream stages can replay and audit: workload package, source graph, lowering report or not-needed marker, executable graph or summary view when applicable, workflow metadata, required coverage, provenance, and adapter-domain validation status.

#### Scenario: Step2 receives workload analysis artifacts
- **WHEN** workload analysis completes for any supported family
- **THEN** Step2 receives persisted generic artifacts and does not depend on hidden adapter state or in-memory parser objects

#### Scenario: Unsupported dynamic behavior is explicit
- **WHEN** a workload contains unsupported dynamic control, unbounded loops, recursion, or undeclared stateful behavior
- **THEN** workload analysis emits a diagnostic lowering status and prevents trusted downstream claims until an adapter summary, bound, or backend-native representation is supplied

### Requirement: Domain correctness remains adapter-owned
The system SHALL separate generic timing/resource evidence from domain correctness. Generic DSE evidence MAY support latency, energy, utilization, data movement, bottleneck, and feasibility claims. Accuracy, physics correctness, solver convergence, query equivalence, recall, or graph-result equivalence SHALL require adapter-owned validation evidence.

#### Scenario: Timing evidence does not imply domain correctness
- **WHEN** a non-QE workload has complete SystemC or gem5+SystemC timing evidence but lacks adapter-domain validation artifacts
- **THEN** the final report labels timing/resource claims as available and domain correctness claims as unavailable or unclaimed
