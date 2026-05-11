## Context

The prior broad-workload change established that DSE v2 should analyze AI/tensor, sparse, stencil/streaming, graph, database/vector-search, DFT/QE, and custom workloads through domain-neutral artifacts. The implementation still has a structural leak: `DftQeAdapter`, `DFT_QE_REQUIRED_COVERAGE`, `dft_qe` workflow branches, QE mapping seeds, `required_qe_scf_phases`, and QE-specific report language are core concepts.

This change is an architecture cleanup, not another incremental QE patch. The target is a profile-first ingestion model in which core DSE never imports QE graph builders, QE constants, or QE adapter classes. QE may remain only as a reference workload profile and importer plugin that produces the same generic artifacts as every other workload source.

## Goals / Non-Goals

**Goals:**
- Replace privileged core adapters with a `WorkloadImporter` plugin boundary.
- Make `WorkloadProfile` the declarative source of accepted sources, lowering policy, coverage, mapping preferences, unavailable metrics, validation boundaries, and claim boundaries.
- Remove core branches keyed on `dft_qe`, `qe_scf`, `adapter_id == "dft_qe"`, or QE phase names.
- Keep Step1/Step2/Step3 artifact contracts stable where possible: downstream stages should carry profile/importer metadata, not hidden plugin state.
- Preserve a QE reference path only as a normal profile/importer fixture.

**Non-Goals:**
- Build production importers for ONNX, Matrix Market, SQL plans, graph datasets, stencil DSLs, or QE trace parsing.
- Remove existing QE reference graph code if it remains useful as fixture data behind a plugin boundary.
- Rewrite simulator backends, optimization algorithms, or architecture catalogs.
- Grant domain correctness claims from generic timing/resource evidence.

## Decisions

### Decision 1: Introduce `WorkloadProfile` as the top-level declarative contract

`WorkloadProfile` will absorb the current role of `WorkloadWorkflow` and extend it with profile id/version, accepted source kinds, lowering policy, required coverage, mapping preferences, unavailable metrics, domain validation requirements, claim-boundary defaults, and optional plugin metadata. Core stages resolve a profile and then process its data generically.

Alternative considered: keep `WorkloadWorkflow` as-is and only rename `DftQeAdapter`. This was rejected because the existing workflow layer still allows QE coverage and mapping seeds to appear as core defaults rather than profile data.

### Decision 2: Replace `WorkloadAdapter` with `WorkloadImporter`

Importers translate source payloads into `WorkloadPackage + ComputeGraph` using an explicitly selected profile. The importer contract is source-format oriented: `import(source, profile, parameters) -> WorkloadPackage`. It does not own global coverage rules, mapping policy defaults, or report wording; those live in the profile.

Alternative considered: keep one universal `generic_json` importer only. This was rejected because real source formats need parsing/provenance code, but that code must be plugin-owned rather than core-owned.

### Decision 3: Remove QE from core dependency graph

Core modules under workload, mapping, evidence, reporting, and pilot orchestration must not import QE graph builders, QE constants, or QE adapter classes. A QE reference importer may call QE fixture builders, but only from plugin/fixture code that the core registry loads as data or optional plugin.

Alternative considered: keep `DftQeAdapter` as a thin wrapper. This was rejected because it preserves `dft_qe` as a privileged architecture concept and encourages future workload-specific wrappers in core.

### Decision 4: Coverage and mapping preferences are profile data

Required coverage, phase labels, seed policy ids, preferred target hints, unavailable metrics, and domain correctness wording must be profile-supplied. If a profile does not declare coverage, the default is lowered executable graph nodes/regions. Mapping search consumes generic op types, tensor sizes, resource capabilities, and profile-supplied preferences without special branches.

Alternative considered: keep QE constants and add similar constants for other families. This was rejected as the exact anti-pattern the change is meant to remove.

### Decision 5: Evidence/report schemas remain generic and backward-compatible where possible

Step3 and final reports should expose `profile_id`, `importer_id`, `required_coverage`, `missing_required_coverage`, `domain_validation`, and `unavailable_metrics`. QE-specific fields such as `required_qe_scf_phases` should be removed from generic schemas or emitted only inside profile-domain metadata for compatibility fixtures.

Alternative considered: keep QE-specific fields and set them empty for non-QE workloads. This was rejected because it keeps QE as a public schema axis.

## Risks / Trade-offs

- [Risk] Existing tests and scripts assert `dft_qe` names directly → Mitigation: migrate them to profile/importer assertions and keep a QE reference regression through the generic path.
- [Risk] Removing `required_qe_scf_phases` may break downstream consumers → Mitigation: provide a generic `required_coverage` field and, if needed, a temporary profile-domain compatibility section outside the core schema.
- [Risk] Importer/profile split could duplicate data → Mitigation: profile owns declarative policy; importer owns source parsing/provenance only.
- [Risk] The architecture cleanup may look like a large refactor → Mitigation: keep artifact shapes stable and focus implementation on removing core domain branches.

## Migration Plan

1. Add `WorkloadProfile` and `WorkloadImporter` contracts and update OpenSpec terminology.
2. Refactor workload registry exports so profile registry and importer registry are distinct.
3. Move QE required coverage, mapping preferences, unavailable metrics, and report wording into a reference profile/plugin fixture.
4. Remove `DftQeAdapter`, `DFT_QE_REQUIRED_COVERAGE`, and `dft_qe` branches from core workload, mapping, evidence, reporting, and pilot paths.
5. Update tests so representative non-QE profiles and QE reference profile both flow through the same generic path.
6. Validate focused workload/profile/importer, Step2, Step3, report, and OpenSpec tests.

Rollback is a normal source revert: no external data or schema migration is required before archive. If compatibility is needed, retain a thin CLI alias that delegates to the generic profile-driven entrypoint without reintroducing core QE branches.

## Open Questions

- Should the first implementation keep a temporary `qe_scf_reference` profile id, or should it use a fully generic id such as `scientific_dft_reference` with QE metadata only in domain fields?
- Should profile definitions live in Python data first, JSON/YAML files first, or both with Python loading a file-backed registry?
