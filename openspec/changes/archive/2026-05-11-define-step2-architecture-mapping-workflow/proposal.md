## Why

Step1 now emits a domain-neutral workload package, executable graph, workflow metadata, required coverage, and source-to-executable provenance. Step2 needs an equally explicit architecture/mapping contract so those Step1 outputs can be consumed by a generic DSE pipeline without falling back to QE-specific architecture assumptions, hand-written mappings, or undocumented candidate-selection shortcuts.

## What Changes

- Define Step2 as the architecture-catalog, DesignPoint assembly, legality-matrix, seed-mapping, mapping-search, promotion, and feedback handoff layer between Step1 workload lowering and Step3+ simulation/evidence.
- Specify the exact Step1 input artifacts Step2 consumes and the exact artifacts Step2 must produce for later simulation, evidence, convergence, and final-report stages.
- Require architecture families, component types, architecture instances, simulation bindings, constraints, and status labels to be explicit, versioned, and auditable.
- Require mapping search to be workload-family aware through declared workflow metadata, but not hardcoded to QE node names or any single workload family.
- Define acceptance gates for legal mappings, fallback handling, candidate lifecycle, screening/promote decisions, and trusted-vs-candidate-only architecture status.
- Document the Step2 review workflow and remaining implementation handoff so later Step3+ work can consume Step2 artifacts mechanically.

## Capabilities

### New Capabilities
- `step2-architecture-mapping-workflow`: Defines the Step2 workflow contract, inputs, outputs, acceptance gates, audit artifacts, and review checklist for architecture catalog selection, DesignPoint assembly, and mapping/search handoff.

### Modified Capabilities
- `accelerator-system-description`: Clarifies architecture catalog, architecture family, component, constraint, simulation-binding, and trusted-final eligibility requirements needed by Step2.
- `multi-fidelity-dse-evaluation`: Clarifies mapping/search, screening, promotion, candidate lifecycle, feedback sample, and low-fidelity non-final boundaries for Step2.
- `end-to-end-dse-workflow`: Adds Step2 stage boundaries and handoff artifacts between workload lowering and simulation/evidence stages.
- `generic-dse-ir-contract`: Clarifies that Step2 consumes only Step1 generic workload/lowering artifacts and emits replayable DesignPoint/mapping artifacts without domain-specific hidden state.

## Impact

- Affected docs/specs: `docs/architecture/generic_dse_framework_design_spec_v2.md`, `docs/architecture/generic_dse_openspec_traceability_matrix_v2.md`, OpenSpec architecture/mapping/workflow/IR specs.
- Affected implementation expectations: architecture catalog schema, catalog validation, DesignPoint generation, mapping search, mapping artifacts, promotion decisions, and feedback state.
- No new external dependencies are required.
- No QE source tree changes are required.
