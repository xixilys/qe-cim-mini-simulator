## Why

The current generic DSE architecture still privileges DFT/QE through a core `DftQeAdapter`, QE coverage constants, QE mapping seeds, and QE-specific evidence/report fields. This blocks the intended multi-workload architecture because each new workload family would otherwise require another core special case instead of entering through a uniform profile/importer boundary.

## What Changes

- Introduce profile-first workload ingestion: core stages consume `WorkloadPackage`, `ComputeGraph`, and resolved `WorkloadProfile` data, not domain-specific adapter classes.
- Introduce plugin workload importers that translate sources into generic workload packages without adding source-domain branches to core DSE code.
- **BREAKING**: remove `DftQeAdapter` as a privileged core adapter concept; QE may remain only as a reference profile/importer plugin or test fixture.
- Move QE required coverage, mapping preferences, unavailable metrics, and correctness text out of core constants/branches and into profile/plugin data.
- Require Step1/Step2/Step3/evidence/reporting paths to process workload metadata generically and reject reintroduction of `dft_qe` privileged branches.

## Non-goals

- Do not implement production ONNX, Matrix Market, SQL, graph dataset, stencil DSL, or QE trace importers in this change.
- Do not remove QE reference graph fixtures if they are still useful for regression coverage.
- Do not replace `ComputeGraph`, `WorkloadPackage`, Step2 mapping artifacts, Step3 evidence artifacts, or simulator backends.
- Do not make generic timing evidence imply domain correctness.

## Capabilities

### New Capabilities
- `workload-profile-contract`: Defines declarative workload profiles as the source of accepted sources, lowering policy, required coverage, mapping preferences, unavailable metrics, validation boundaries, and claim boundaries.
- `workload-importer-registry`: Defines plugin workload importers that translate external sources or generated fixtures into `WorkloadPackage` + `ComputeGraph` using a selected workload profile.

### Modified Capabilities
- `generic-dse-ir-contract`: Replace core adapter terminology with profile/importer terminology and prohibit core imports or branches for QE or any workload family.
- `generic-workload-workflows`: Recast workflow templates as workload profiles and remove adapter-specific QE coverage language from the generic contract.
- `dft-qe-workload-adapter`: Downgrade DFT/QE from a core adapter capability to a reference workload profile/importer plugin capability.
- `step1-workflow-contract`: Change Step1 from adapter-selection semantics to profile resolution plus importer execution semantics.
- `step2-architecture-mapping-workflow`: Require mapping preferences to come from generic profile metadata rather than QE-specific seeds or branches.
- `step3-simulation-evidence-workflow`: Require evidence coverage and domain validation text to come from profile metadata without QE-specific fields.
- `end-to-end-dse-workflow`: Require the complete flow to remain profile-driven from ingestion through final report.
- `generic-simulation-backend`: Require backend requests to carry profile-derived generic metadata without QE-specific request fields.
- `multi-fidelity-dse-evaluation`: Require trust gates and promotion labels to use profile/importer metadata without privileged workload-family exceptions.

## Impact

- Affects OpenSpec workload, Step1, Step2, Step3, backend, and trust-gate contracts.
- Affects DSE v2 workload ingestion, registry exports, workflow/profile metadata, mapping seed generation, evidence serialization, final reporting, pilot CLI, and tests.
- Requires migration of QE-specific constants and assertions into profile/plugin fixtures while preserving generic regression coverage.
