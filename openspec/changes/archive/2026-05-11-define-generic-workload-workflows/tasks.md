## 1. OpenSpec Workflow Contract

- [x] 1.1 Add `generic-workload-workflows` requirements covering family workflow templates, adapter-required coverage, ML/tensor, sparse linear algebra, stencil/streaming, graph analytics, database/vector search, dynamic/custom workflows, and final claim separation.
- [x] 1.2 Add OpenSpec deltas for generic IR, end-to-end workflow, generic simulation backend, and DFT/QE adapter coverage boundaries.

## 2. Handbook Update

- [x] 2.1 Update the architecture handbook with a workload-family workflow matrix and per-family source, graph, lowering, mapping, simulation, domain-validation, and claim-boundary definitions.
- [x] 2.2 Explicitly document that DFT/QE SCF phases are adapter coverage only, while non-QE workloads use adapter-declared or executable-graph coverage.

## 3. Validation

- [x] 3.1 Run OpenSpec strict validation for the new change and all specs.
- [x] 3.2 Record the validated artifacts and remaining implementation handoff notes for later Step2+ goals.
