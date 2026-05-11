## ADDED Requirements

### Requirement: End-to-end workflow supports broad workload families
The end-to-end DSE workflow SHALL support broad workload analysis outputs from any supported workload family as the normal entry point into mapping, simulation, evidence, and reporting. The workflow SHALL NOT special-case DFT/QE as the only route capable of producing complete run artifacts.

#### Scenario: Non-QE full flow produces standard artifacts
- **WHEN** an ML/tensor, sparse, stencil, graph analytics, database/vector-search, or custom workload has valid workload analysis output, mapping, and backend binding
- **THEN** the full DSE run produces the same classes of artifacts as a QE run: workload package, graph, lowering report, mapping artifacts, simulation request/result, verdict, claim validation, final report, and manifest

#### Scenario: End-to-end report names adapter boundary
- **WHEN** the final report summarizes a completed run
- **THEN** it identifies the workload family, adapter id/version, generic timing/resource claims, adapter-domain validation status, and limitations without implying that QE is the default workload model
