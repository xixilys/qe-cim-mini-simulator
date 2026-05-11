## 1. Profile and Importer Contracts

- [ ] 1.0 Reconcile OpenSpec deltas so replaced adapter semantics are expressed as `MODIFIED` or `REMOVED` requirements before implementation begins.
- [ ] 1.1 Add `WorkloadProfile` data model and registry, preserving existing workflow fields as profile fields.
- [ ] 1.2 Add `WorkloadImporter` interface and importer registry separate from profile registry.
- [ ] 1.3 Update `WorkloadPackage` serialization to carry profile id/version and importer id/version while preserving opaque domain metadata.
- [ ] 1.4 Add tests proving new profiles/importers can be registered without changing core IR or backend request schemas.

## 2. Remove DFT/QE Core Privilege

- [ ] 2.1 Remove `DftQeAdapter` from core workload adapter exports and default core registry.
- [ ] 2.2 Move QE required coverage, mapping preferences, unavailable metrics, and correctness wording into a QE reference profile/plugin fixture.
- [ ] 2.3 Remove `DFT_QE_REQUIRED_COVERAGE` as a core constant and remove `dft_qe` fallback logic from required coverage resolution.
- [ ] 2.4 Update QE reference tests to assert QE enters through the generic profile/importer path.

## 3. Generic Step1/Step2/Step3 Consumers

- [ ] 3.1 Update Step1 to resolve profile first, validate importer/profile/source-kind compatibility, and persist profile/importer manifests.
- [ ] 3.2 Update Step2 mapping search to consume profile mapping preferences without hardcoded QE seed names or preferred targets.
- [ ] 3.3 Update Step3 evidence generation to validate generic `required_coverage` and stop emitting QE-specific generic schema fields.
- [ ] 3.4 Update final reporting to use profile/importer metadata for unavailable metrics, limitations, and domain validation text.

## 4. CLI, Documentation, and Compatibility

- [ ] 4.1 Generalize full-flow pilot CLI around `--profile`, `--importer`, `--source-kind`, and source/generator parameters.
- [ ] 4.2 Keep any QE command as a compatibility wrapper only if it delegates to the generic profile-driven path.
- [ ] 4.3 Update OpenSpec-facing and DSE v2 docs so QE is described as a reference profile/importer, not as a core adapter.

## 5. Verification

- [ ] 5.1 Run focused profile/importer, workload package, graph lowering, Step2 mapping, Step3 evidence, and final report tests.
- [ ] 5.2 Run QE reference regression through the generic profile/importer path.
- [ ] 5.3 Run OpenSpec strict validation for `remove-dft-qe-core-adapter`.
- [ ] 5.4 Run a manual generic workload ingestion or full-flow command and record output showing profile/importer metadata without QE-specific core fields.
