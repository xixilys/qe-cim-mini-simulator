## Why

The DSE v2 implementation already contains domain-neutral workload abstractions, but the project narrative and several workflow surfaces still read as QE-first. This change makes the intended contract explicit: the workload stage is a broad workload analysis system for AI, scientific computing, sparse/graph/database, streaming, and custom computations, with QE retained as one reference adapter.

## What Changes

- Reframe workload ingestion as a domain-neutral `WorkloadPackage` + `ComputeGraph` pipeline rather than a QE SCF pipeline with generic extensions.
- Require all workload-family behavior, coverage, validation, and domain metrics to live behind adapter/workflow metadata.
- Keep DFT/QE-specific phases, correctness labels, and mapping seeds scoped to the `dft_qe` adapter.
- Add implementation and documentation acceptance criteria for non-QE workloads to pass through Step1 workload analysis into Step2 mapping and Step3 evidence without QE fields.
- No breaking changes to existing QE reference flows; compatibility remains through the adapter boundary.

## Non-goals

- Do not implement production importers for every external format such as ONNX, Matrix Market, SQL plans, or graph exchange formats in this change.
- Do not remove the existing QE adapter, QE tests, or QE evidence contracts.
- Do not replace the SystemC/gem5 backend stack or introduce new optimizer algorithms.

## Capabilities

### New Capabilities
- `broad-workload-analysis-system`: Defines the top-level contract for a broad workload analysis system that treats AI, scientific computing, sparse/graph/database, streaming, and custom workloads as first-class inputs.

### Modified Capabilities
- `generic-dse-ir-contract`: Clarify that core IR validation and mapping must reject domain leakage from any workload family, not only QE.
- `generic-workload-workflows`: Strengthen workflow requirements so built-in non-QE families are acceptance paths, not examples.
- `end-to-end-dse-workflow`: Require non-QE workload packages to reach Step2/Step3 artifacts without QE-specific fields.
- `step2-architecture-mapping-workflow`: Clarify generic mapping artifact requirements for non-QE workloads.
- `step3-simulation-evidence-workflow`: Clarify generic evidence and claim-boundary behavior for non-QE workloads.

## Impact

- Affects OpenSpec contracts under `openspec/specs/` and this change's delta specs.
- Affects DSE v2 workload ingestion, workflow, mapping, evidence, reporting, and tests under `dse_v2/`.
- Affects user-facing DSE v2 documentation that currently frames the project as QE-first.
