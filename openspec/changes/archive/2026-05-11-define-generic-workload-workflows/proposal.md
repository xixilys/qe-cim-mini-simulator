## Why

The generic DSE design now accepts non-QE `WorkloadPackage` inputs, but the handbook and OpenSpec contracts do not yet define the complete workflow obligations for each major workload family. Without those family workflows, later implementation steps can accidentally reintroduce QE-only coverage gates, ambiguous adapter correctness claims, or workload-specific shortcuts that cannot be audited.

## What Changes

- Define a new OpenSpec capability for generic workload-family workflows covering ML/tensor graphs, sparse linear algebra, stencil/streaming pipelines, graph analytics, database/vector-search pipelines, DFT/QE, dynamic-control workloads, and custom scientific graphs.
- Specify the per-family sequence from source ingestion through adapter validation, graph lowering, mapping policies, simulation/evidence, adapter-domain validation, and final claim gating.
- Require each workload adapter to declare coverage nodes/regions, domain metrics, unsupported constructs, and correctness boundaries instead of relying on hardcoded QE phase names.
- Update the architecture handbook with a reviewable workload workflow matrix so future Step2+ implementation can target one family at a time without changing the core DSE contract.
- Preserve existing smoke/fixed-timing restrictions: diagnostic workloads and smoke-only runs remain invalid for trusted final checks.

## Capabilities

### New Capabilities
- `generic-workload-workflows`: Defines the required workflow contracts, adapter obligations, coverage gates, domain-validation boundaries, and evidence expectations for supported workload families in the generic DSE system.

### Modified Capabilities
- `generic-dse-ir-contract`: Clarifies that `WorkloadPackage` adapters must declare required coverage and domain validation boundaries for each workload family.
- `end-to-end-dse-workflow`: Extends the DSE stage contract so coverage and correctness gates are adapter/workload-family driven rather than QE-phase driven.
- `generic-simulation-backend`: Clarifies that backend request/evidence coverage must use adapter-declared executable nodes/regions for all workload families, with DFT/QE as only one adapter example.
- `dft-qe-workload-adapter`: Clarifies DFT/QE as one concrete workload workflow with SCF phase coverage, not the default coverage model for other workloads.

## Impact

- Affected docs/specs: `docs/architecture/generic_dse_framework_design_spec_v2.md`, OpenSpec workload/IR/workflow/backend/DFT specs.
- Affected implementation expectations: workload adapters, graph lowering, mapping search seeds, evidence generation, final report validation, and future tests for non-QE workloads.
- No new external dependencies are required.
- No QE source tree changes are required.
