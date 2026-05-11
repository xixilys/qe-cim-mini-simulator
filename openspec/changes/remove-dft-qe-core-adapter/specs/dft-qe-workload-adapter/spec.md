## ADDED Requirements

### Requirement: DFT/QE is a reference profile and importer plugin
DFT/QE support SHALL be represented as a reference workload profile plus an optional workload importer plugin. It SHALL NOT be a core adapter capability, core coverage constant, core mapping branch, core evidence schema field, or core report branch.

#### Scenario: QE reference graph enters through importer plugin
- **WHEN** a QE reference workload is generated or imported
- **THEN** a QE-compatible importer plugin emits a generic WorkloadPackage and ComputeGraph using a selected profile without core DSE importing QE builder code

#### Scenario: QE-specific information stays profile/plugin owned
- **WHEN** QE phase names, tensor parameters, calibration notes, or correctness warnings are needed
- **THEN** they are recorded in profile data, importer provenance, or domain metadata rather than generic core fields

## REMOVED Requirements

### Requirement: DFT/QE adapter is one registered workload adapter
**Reason**: The architecture no longer permits a privileged core adapter concept for DFT/QE or any other workload family.
**Migration**: Replace the DFT/QE adapter with a QE reference workload profile and optional importer plugin that emits generic WorkloadPackage and ComputeGraph artifacts.

### Requirement: DFT/QE adapter maps SCF workflow to generic ComputeGraph
**Reason**: SCF graph construction is no longer specified as an adapter responsibility in core contracts.
**Migration**: Express QE SCF graph construction as optional QE reference importer/plugin behavior governed by a workload profile.

### Requirement: Canonical QE SCF graph includes the expected operation chain
**Reason**: Canonical QE graph contents are fixture/profile details, not generic DSE core requirements.
**Migration**: Move the operation-chain requirement to QE reference profile/plugin tests if QE regression coverage is retained.

### Requirement: DFT tensor and workload parameters are explicit
**Reason**: DFT tensor parameters are domain metadata owned by the QE reference profile/importer, not a core adapter capability.
**Migration**: Preserve these parameters in profile/importer domain metadata and validation artifacts.

### Requirement: Trace ingestion preserves provenance and units
**Reason**: Trace ingestion is source-format importer behavior rather than a DFT adapter core capability.
**Migration**: Require provenance and units through the generic workload importer registry contract and QE importer plugin tests.

### Requirement: DFT adapter supports reference and reduced workloads
**Reason**: Reference/reduced workload handling is profile claim-boundary behavior, not DFT adapter behavior.
**Migration**: Encode full, reduced, smoke, and diagnostic boundaries in QE reference profile data and generic trust gates.

### Requirement: DFT mapping policies are configurable
**Reason**: Mapping preferences must be profile data consumed generically by Step2, not adapter methods.
**Migration**: Move host-only, operator-sweep, hardware-diagonalization, and fallback preferences into QE reference profile mapping preferences.

### Requirement: DFT metrics include domain and framework views
**Reason**: Domain metrics are profile/importer-owned unavailable/validation metadata and should not require a core DFT adapter.
**Migration**: Store DFT-domain metric labels and validation expectations in QE reference profile data.

### Requirement: Calibration compares model output against QE evidence
**Reason**: Calibration against QE evidence is plugin/profile-domain validation, not generic core adapter behavior.
**Migration**: Keep calibration artifacts under QE reference importer/profile validation evidence.

### Requirement: DFT adapter respects algorithm-freeze priorities
**Reason**: Algorithm-freeze priorities are project/domain guidance and not a generic DSE core adapter requirement.
**Migration**: Preserve this guidance in QE reference documentation or plugin tests, outside core workload ingestion contracts.

### Requirement: DFT regression suite covers generic and domain-specific behavior
**Reason**: Regression coverage should test the QE reference profile/importer through the generic path rather than a DFT adapter.
**Migration**: Replace adapter tests with generic profile/importer regression tests that include QE as one reference fixture.
