## ADDED Requirements

### Requirement: Step1 resolves profile before importer execution
Step1 SHALL resolve a workload profile before invoking a workload importer. Step1 SHALL validate that the requested source kind is accepted by the profile and supported by the importer before graph construction begins.

#### Scenario: Valid profile and importer produce Step1 artifacts
- **WHEN** Step1 receives a known profile id, known importer id, supported source kind, and valid source payload
- **THEN** it emits `step1_status.json`, `workload_package.json`, `workload_graph.json`, `graph_lowering_report.json`, importer manifest, profile manifest, and artifact validation output

#### Scenario: Profile/importer mismatch blocks ingestion
- **WHEN** the selected importer does not support the selected profile or source kind
- **THEN** Step1 returns a structured blocked status and does not hand partial artifacts to Step2

### Requirement: Step1 does not select privileged domain adapters
Step1 SHALL NOT select special core adapters based on domain names. All domain-specific source handling SHALL occur through importer plugins and profile data.

#### Scenario: QE source follows generic Step1 path
- **WHEN** Step1 ingests a QE reference source
- **THEN** it uses the same profile resolution, importer execution, graph lowering, and artifact validation path as non-QE sources

## MODIFIED Requirements

### Requirement: Step 1 is a persisted workflow boundary
Step 1 SHALL consume profile-selected importer input, produce validated workload artifacts, and persist all outputs to disk. Step 2 SHALL consume Step 1 artifacts from disk, not from in-memory Python objects passed directly from Step 1.

#### Scenario: Step 1 produces artifact directory
- **WHEN** `run_step1_workload_ingestion_workflow()` completes
- **THEN** the output directory contains `step1_status.json`, `workload_package.json`, `workload_graph.json`, `graph_lowering_report.json`, `profile_manifest.json`, `importer_manifest.json`, and `step1_artifact_validation.json`

#### Scenario: Step 2 loads Step 1 artifacts from disk
- **WHEN** Step 2 begins execution
- **THEN** it loads `workload_package.json`, `workload_graph.json`, profile metadata, and importer metadata from the Step 1 output directory, not from a Python object reference

#### Scenario: Step 1 artifacts support replay
- **WHEN** an auditor reviews a DSE run
- **THEN** the Step 1 artifact directory contains sufficient information to reconstruct the workload ingestion without re-running the importer


### Requirement: Step 1 validates adapter input before graph construction
Step 1 SHALL validate profile selection, importer selection, source-kind compatibility, source completeness, and supported source format before constructing the ComputeGraph.

#### Scenario: Invalid adapter input is rejected
- **WHEN** an importer receives invalid input (missing required fields, unsupported source kind, malformed parameters, or profile/importer mismatch)
- **THEN** Step 1 returns `step1_status.json` with `status="blocked_invalid_importer_input"` and structured validation errors

#### Scenario: Adapter version mismatch is detected
- **WHEN** an importer or profile declares a version incompatible with the framework's supported schema
- **THEN** Step 1 blocks ingestion and reports `importer_or_profile_version_incompatible` with expected and actual versions

#### Scenario: Unknown adapter is rejected
- **WHEN** a workload references an importer or profile not registered in the importer/profile registries
- **THEN** Step 1 returns `status="blocked_unknown_importer_or_profile"` and lists available importers and profiles

### Requirement: Step 1 supports adapter registry introspection
Step 1 SHALL provide profile registry and importer registry information to enable discovery of supported workload profiles, source kinds, importer capabilities, and compatibility between profiles and importers.

#### Scenario: Adapter manifest is generated
- **WHEN** Step 1 runs
- **THEN** `profile_manifest.json` and `importer_manifest.json` list registered profiles, registered importers, supported source kinds, versions, compatibility, and default profile mapping preferences

#### Scenario: Adapter capabilities are discoverable
- **WHEN** a user queries available workload inputs
- **THEN** the system returns profile and importer metadata without requiring workload ingestion

### Requirement: Step 1 records complete provenance
Step 1 SHALL record complete provenance for audit, including profile identity, importer identity, input source, timestamp, framework version, and environment.

#### Scenario: Provenance is recorded
- **WHEN** Step 1 completes
- **THEN** `step1_status.json` includes `provenance` block with `profile_id`, `profile_version`, `importer_id`, `importer_version`, `source_path`, `timestamp`, `framework_version`, and `environment_summary`

#### Scenario: Provenance supports reproduction
- **WHEN** an auditor reviews a DSE run
- **THEN** the provenance information is sufficient to identify the exact profile, importer version, and input that produced the workload

### Requirement: Step 1 declares workload coverage and claim boundary
Step 1 SHALL record the profile-derived required coverage and package claim boundary in the persisted artifacts.

#### Scenario: Adapter declares required coverage
- **WHEN** a selected profile declares `required_coverage=["load_csr", "spmv", "norm"]`
- **THEN** `workload_package.json` and `graph_lowering_report.json` preserve this coverage declaration and Step 3 uses it for coverage validation

#### Scenario: Diagnostic workloads are labeled
- **WHEN** a profile or package declares `claim_boundary="smoke"` or `"diagnostic"`
- **THEN** `step1_status.json` records the diagnostic boundary and TrustGate prevents the workload from entering trusted final ranking

#### Scenario: Full workloads are eligible
- **WHEN** a workload has `claim_boundary="full_workload"` and lowering succeeds
- **THEN** the workload is marked `full_workload_eligible=true` and may proceed to trusted evaluation

### Requirement: Step 1 artifacts are versioned and validated
All Step 1 artifacts SHALL carry schema version identifiers and SHALL be validated before handoff to Step 2.

#### Scenario: Artifacts carry schema version
- **WHEN** `workload_package.json` is written
- **THEN** it includes a `schema_version` field and profile/importer identity fields supported by the current workload package contract

#### Scenario: Artifact validation checks completeness
- **WHEN** Step 1 completes
- **THEN** `step1_artifact_validation.json` lists all required artifacts, their presence, schema versions, and checksums, including profile and importer manifests

#### Scenario: Missing artifacts block Step 2
- **WHEN** Step 2 loads a Step 1 directory with missing required artifacts
- **THEN** Step 2 returns `status="blocked_incomplete_step1_handoff"` and lists missing artifacts

## REMOVED Requirements

### Step 1 Artifact Schema
**Reason**: The old illustrative schema hardcodes adapter-era fields such as `adapter_id`, `adapter_version`, `adapter_manifest.json`, and adapter-specific blocked statuses.
**Migration**: Replace the illustrative schema with profile/importer-aware artifacts: `profile_id`, `profile_version`, `importer_id`, `importer_version`, `profile_manifest.json`, `importer_manifest.json`, and profile/importer blocked statuses.
