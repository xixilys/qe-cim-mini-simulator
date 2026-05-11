## ADDED Requirements

### Requirement: End-to-end workflow is workload-family driven
The end-to-end DSE workflow SHALL execute the same generic stages for all workload families while allowing each adapter to declare family-specific coverage, lowering, mapping, and validation requirements. The stages SHALL be: source ingestion, WorkloadPackage validation, graph validation, graph lowering, architecture/catalog selection, mapping search, simulation, evidence export, adapter-domain validation, feedback update, convergence decision, and final report generation.

#### Scenario: Non-QE workload follows the same stages
- **WHEN** a non-QE workload such as ML, sparse, stencil, graph analytics, database/vector search, or custom scientific graph is selected
- **THEN** the workflow emits the same core artifact classes as DFT/QE runs, including workload package, source graph, graph-lowering report, mapping artifacts, simulation request/result, verdict, and final report

#### Scenario: Adapter coverage controls phase coverage
- **WHEN** the workflow validates phase or node coverage for a full-flow run
- **THEN** it uses adapter-declared required coverage or lowered executable graph nodes rather than a global QE phase list

### Requirement: Adapter-domain validation is a separate stage
The workflow SHALL include an optional adapter-domain validation stage after simulation and before final claim validation. This stage SHALL consume adapter-defined reference outputs, tolerances, trace baselines, residual thresholds, accuracy checks, query equivalence checks, or unavailable-metric declarations. Generic timing validation SHALL remain separate from domain correctness validation.

#### Scenario: Domain validation evidence is cited for correctness claims
- **WHEN** a final report claims ML accuracy, sparse residual convergence, stencil numerical error, graph traversal equivalence, database query correctness, vector-search recall, or DFT/QE physical correctness
- **THEN** it cites adapter-domain validation evidence in addition to generic SystemC/gem5+SystemC timing evidence

#### Scenario: Missing domain validator limits report claims
- **WHEN** no adapter-domain validator exists for a workload family
- **THEN** the workflow may report timing/resource feasibility but labels domain correctness claims unavailable or unclaimed
