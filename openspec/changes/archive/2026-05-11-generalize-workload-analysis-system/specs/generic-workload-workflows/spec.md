## ADDED Requirements

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
