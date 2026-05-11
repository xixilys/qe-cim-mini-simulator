# step1-workflow-contract Specification

## Purpose
Define the Step 1 workload ingestion workflow contract, including adapter selection, workload validation, graph construction, graph lowering, artifact persistence, and the stable handoff to Step 2. Step 1 SHALL be the first persisted boundary in the end-to-end DSE workflow.

## Requirements

### Requirement: Step 1 is a persisted workflow boundary
Step 1 SHALL consume adapter input, produce validated workload artifacts, and persist all outputs to disk. Step 2 SHALL consume Step 1 artifacts from disk, not from in-memory Python objects passed directly from Step 1.

#### Scenario: Step 1 produces artifact directory
- **WHEN** `run_step1_workload_ingestion_workflow()` completes
- **THEN** the output directory contains `step1_status.json`, `workload_package.json`, `workload_graph.json`, `graph_lowering_report.json`, `adapter_manifest.json`, and `step1_artifact_validation.json`

#### Scenario: Step 2 loads Step 1 artifacts from disk
- **WHEN** Step 2 begins execution
- **THEN** it loads `workload_package.json` and `workload_graph.json` from the Step 1 output directory, not from a Python object reference

#### Scenario: Step 1 artifacts support replay
- **WHEN** an auditor reviews a DSE run
- **THEN** the Step 1 artifact directory contains sufficient information to reconstruct the workload ingestion without re-running the adapter

### Requirement: Step 1 validates adapter input before graph construction
Step 1 SHALL validate adapter input for completeness, correctness, and supported source kind before constructing the ComputeGraph.

#### Scenario: Invalid adapter input is rejected
- **WHEN** an adapter emits invalid input (missing required fields, unsupported source kind, malformed parameters)
- **THEN** Step 1 returns `step1_status.json` with `status="blocked_invalid_adapter_input"` and structured validation errors

#### Scenario: Adapter version mismatch is detected
- **WHEN** an adapter declares a version incompatible with the framework's supported adapter schema
- **THEN** Step 1 blocks ingestion and reports `adapter_version_incompatible` with expected and actual versions

#### Scenario: Unknown adapter is rejected
- **WHEN** a workload references an adapter not registered in the adapter registry
- **THEN** Step 1 returns `status="blocked_unknown_adapter"` and lists available adapters

### Requirement: Step 1 constructs domain-neutral ComputeGraph
Step 1 SHALL construct a ComputeGraph that uses only generic IR constructs. Domain-specific node names, phase templates, or operator enums SHALL NOT be required by core graph validation.

#### Scenario: Generic graph passes validation
- **WHEN** an adapter emits a graph with custom `op_type` values and generic tensor/resource attributes
- **THEN** core graph validation accepts the graph without requiring domain-specific field presence

#### Scenario: QE-specific fields are opaque
- **WHEN** a DFT/QE adapter includes `npw`, `nkb`, `h_psi`, or other QE-specific attributes
- **THEN** these fields are preserved in `node.attributes` but core validation does not require or interpret them

#### Scenario: Core validation rejects domain-hardcoded checks
- **WHEN** core graph validation encounters a check for QE-specific node names (e.g., `h_psi`, `diagonalize`, `mix_rho`)
- **THEN** the validation fails with `domain_leakage_error` because core IR must be domain-neutral

### Requirement: Step 1 performs graph lowering with full provenance
Step 1 SHALL lower the source ComputeGraph into an executable view and record complete provenance in `graph_lowering_report.json`.

#### Scenario: Lowering produces executable graph
- **WHEN** a ComputeGraph contains loops, hierarchy, or control flow
- **THEN** Step 1 produces `executable_graph.json` with bounded, executable constructs and records the lowering policy

#### Scenario: Lowering preserves source-to-executable mapping
- **WHEN** a source graph node is expanded or summarized during lowering
- **THEN** `graph_lowering_report.json` records the `source_to_executable_nodes` mapping for traceability

#### Scenario: Unsupported graphs are blocked
- **WHEN** a graph contains dynamic control, recursion, or unbounded iteration that cannot be lowered
- **THEN** Step 1 returns `status="blocked_unsupported_graph"` and prevents the graph from entering Step 2

### Requirement: Step 1 declares workload coverage and claim boundary
Step 1 SHALL record the adapter-declared required coverage and claim boundary in the persisted artifacts.

#### Scenario: Adapter declares required coverage
- **WHEN** an adapter emits a workload with `required_coverage=["load_csr", "spmv", "norm"]`
- **THEN** `workload_package.json` preserves this coverage declaration and Step 3 uses it for phase validation

#### Scenario: Diagnostic workloads are labeled
- **WHEN** an adapter emits a workload with `claim_boundary="smoke"` or `"diagnostic"`
- **THEN** `step1_status.json` records the diagnostic boundary and TrustGate prevents the workload from entering trusted final ranking

#### Scenario: Full workloads are eligible
- **WHEN** an adapter emits a workload with `claim_boundary="full_workload"` and lowering succeeds
- **THEN** the workload is marked `full_workload_eligible=true` and may proceed to trusted evaluation

### Requirement: Step 1 artifacts are versioned and validated
All Step 1 artifacts SHALL carry schema version identifiers and SHALL be validated before handoff to Step 2.

#### Scenario: Artifacts carry schema version
- **WHEN** `workload_package.json` is written
- **THEN** it includes `schema_version` field with value `dse.step1.workload_package.v1`

#### Scenario: Artifact validation checks completeness
- **WHEN** Step 1 completes
- **THEN** `step1_artifact_validation.json` lists all required artifacts, their presence, schema versions, and checksums

#### Scenario: Missing artifacts block Step 2
- **WHEN** Step 2 loads a Step 1 directory with missing required artifacts
- **THEN** Step 2 returns `status="blocked_incomplete_step1_handoff"` and lists missing artifacts

### Requirement: Step 1 supports adapter registry introspection
Step 1 SHALL provide adapter registry information to enable discovery of supported workload families and adapter capabilities.

#### Scenario: Adapter manifest is generated
- **WHEN** Step 1 runs
- **THEN** `adapter_manifest.json` lists all registered adapters, their supported source kinds, versions, and default mapping policies

#### Scenario: Adapter capabilities are discoverable
- **WHEN** a user queries available adapters
- **THEN** the system returns adapter metadata without requiring workload ingestion

### Requirement: Step 1 records complete provenance
Step 1 SHALL record complete provenance for audit, including adapter identity, input source, timestamp, framework version, and environment.

#### Scenario: Provenance is recorded
- **WHEN** Step 1 completes
- **THEN** `step1_status.json` includes `provenance` block with `adapter_id`, `adapter_version`, `source_path`, `timestamp`, `framework_version`, and `environment_summary`

#### Scenario: Provenance supports reproduction
- **WHEN** an auditor reviews a DSE run
- **THEN** the provenance information is sufficient to identify the exact adapter version and input that produced the workload

### Requirement: Step 1 artifact writes are atomic and concurrency-safe
Step 1 SHALL ensure that artifact writes are atomic and safe under concurrent execution. Multiple runs SHALL NOT corrupt shared artifacts or leave partial writes visible to Step 2.

#### Scenario: Concurrent runs use unique run directories
- **WHEN** two Step 1 runs execute concurrently
- **THEN** each run writes to a distinct `run_id` directory and neither overwrites the other's artifacts

#### Scenario: Partial artifact write is quarantined
- **WHEN** a Step 1 run crashes after writing `workload_package.json` but before completing `step1_status.json`
- **THEN** the incomplete run directory is not visible to Step 2 as a valid handoff

#### Scenario: Artifact validation detects corrupted files
- **WHEN** `step1_artifact_validation.json` detects a checksum mismatch or truncated file
- **THEN** Step 1 reports `status="blocked_validation_failed"` and the artifact is not handed off to Step 2

## Step 1 Artifact Schema

### Required Artifacts

| Artifact | File | Description |
|----------|------|-------------|
| Status | `step1_status.json` | Workflow status, provenance, validation results |
| Workload Package | `workload_package.json` | Domain-neutral workload description |
| Workload Graph | `workload_graph.json` | Source ComputeGraph |
| Lowering Report | `graph_lowering_report.json` | Lowering provenance and eligibility |
| Executable Graph | `executable_graph.json` | Lowered executable view (if lowering succeeds) |
| Adapter Manifest | `adapter_manifest.json` | Registry of available adapters |
| Validation | `step1_artifact_validation.json` | Artifact completeness and schema validation |

### step1_status.json Schema

```json
{
  "schema_version": "dse.step1.status.v1",
  "status": "complete | blocked_invalid_adapter_input | blocked_unknown_adapter | blocked_unsupported_graph | blocked_validation_failed",
  "workload_id": "string",
  "workload_family": "string",
  "adapter_id": "string",
  "adapter_version": "string",
  "claim_boundary": "full_workload | smoke | diagnostic | reduced | synthetic",
  "full_workload_eligible": true,
  "provenance": {
    "source_path": "string",
    "timestamp": "ISO-8601",
    "framework_version": "string",
    "environment_summary": "string"
  },
  "artifacts": {
    "workload_package": "workload_package.json",
    "workload_graph": "workload_graph.json",
    "graph_lowering_report": "graph_lowering_report.json",
    "executable_graph": "executable_graph.json"
  },
  "validation": {
    "valid": true,
    "errors": [],
    "warnings": []
  }
}
```
