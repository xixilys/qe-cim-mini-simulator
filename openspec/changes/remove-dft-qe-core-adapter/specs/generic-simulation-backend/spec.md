## ADDED Requirements

### Requirement: Backend requests carry profile-derived generic metadata
Generic simulation backend requests SHALL carry workload graph, tensor/resource metadata, mapping, schedule, profile id/version, importer id/version, required coverage, and domain metadata as generic fields. Backend request schemas SHALL NOT include QE-specific required fields.

#### Scenario: QE reference request remains generic
- **WHEN** a QE reference workload is submitted to the backend
- **THEN** the request remains valid because it carries generic graph and profile metadata, not because it contains QE-specific schema fields

#### Scenario: Backend ignores unknown domain metadata
- **WHEN** a workload includes profile/plugin-owned domain metadata unrelated to timing/resource simulation
- **THEN** the backend preserves or ignores it without treating it as required simulator input

## MODIFIED Requirements

### Requirement: Build, regression, and full-flow pilot commands are reproducible for heterogeneous architectures
The backend SHALL document and support reproducible build/regression commands for C++ generic_sim with **heterogeneous accelerator support**, standalone SystemC timing-level full-workload pilots, and gem5+SystemC validation when the L4 binding is available. The build system SHALL compile the generic heterogeneous backend by default; the legacy 4-Cluster model SHALL be available only through an explicit compile flag. Smoke checks MAY exist only as bring-up diagnostics and SHALL NOT be treated as DSE completion evidence. A final trusted check SHALL require a complete SystemC or gem5+SystemC full-flow simulation for the selected WorkloadPackage and profile; smoke-only, fixed-timing bring-up, legacy smoke conversion, or diagnostic replay paths SHALL fail final trusted validation even when their commands exit successfully.

#### Scenario: C++ heterogeneous backend build is verified
- **WHEN** implementation claims the standalone backend is usable
- **THEN** `cmake --build model/generic_sim_backend/build -j4` or equivalent succeeds and produces a `generic_sim` executable that supports heterogeneous accelerator configurations
- **AND** the build does NOT default to the legacy 4-Cluster model

#### Scenario: Standalone SystemC full-flow pilot is verified before trusted L3 claims
- **WHEN** implementation claims standalone SystemC timing-level evidence is usable for DSE
- **THEN** a SystemC pilot runs the selected full WorkloadPackage, exports the required evidence artifacts, and records gem5+SystemC as `not_run` unless the L4 descriptor/completion path also ran

#### Scenario: gem5 plus SystemC full-flow pilot is verified before L4 claims
- **WHEN** implementation claims L4 integration is usable for DSE
- **THEN** a gem5+SystemC pilot runs the selected full WorkloadPackage through command submission, SystemC timing execution, completion, and evidence export

#### Scenario: QE full-flow uses heterogeneous backend, not legacy 4-Cluster
- **WHEN** a QE reference profile/importer workload is selected and the architecture is a heterogeneous system (e.g., Host+FPGA+CIM)
- **THEN** the generic backend consumes its emitted ComputeGraph through the same heterogeneous request schema used for other workload profiles
- **AND** the backend maps operations to appropriate accelerators based on generic op types, tensor metadata, and resource capabilities, NOT to fixed Cluster A/B/C/D roles or QE-specific schema fields

#### Scenario: Smoke-only evidence fails final validation
- **WHEN** a report, candidate, or run attempts to use smoke output as completion evidence
- **THEN** final validation rejects the trusted claim unless full-flow SystemC evidence or passing `gem5_l4_proof.json` evidence is present
