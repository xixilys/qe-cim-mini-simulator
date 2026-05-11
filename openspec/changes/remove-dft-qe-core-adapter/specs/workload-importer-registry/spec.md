## ADDED Requirements

### Requirement: WorkloadImporter translates sources into generic packages
The system SHALL define `WorkloadImporter` plugins that translate external sources, generated fixtures, or in-memory payloads into `WorkloadPackage` + `ComputeGraph` using a selected `WorkloadProfile`. Importers SHALL own source parsing and provenance, while profiles own policy and claim metadata.

#### Scenario: Importer emits generic artifacts
- **WHEN** an importer ingests a supported source kind
- **THEN** it emits a `WorkloadPackage` with a generic `ComputeGraph`, importer id/version, profile id/version, source provenance, domain metadata, and claim boundary

#### Scenario: Importer cannot alter core schema
- **WHEN** a new importer is added for a source format such as ONNX-like graph, sparse matrix, graph trace, SQL plan, QE fixture, or custom JSON
- **THEN** it does not require changes to core IR classes, mapping search schemas, backend request schemas, or final report schemas

### Requirement: Importer registry is separate from profile registry
The system SHALL maintain separate registries for workload profiles and workload importers. Importer discovery SHALL report source kinds and compatible profiles without making any importer a privileged core path.

#### Scenario: QE reference importer is optional plugin
- **WHEN** the QE reference importer is registered
- **THEN** it appears as one importer compatible with one or more profiles and core DSE modules do not import it directly

#### Scenario: Unknown importer is rejected before graph construction
- **WHEN** Step1 receives an importer id that is not registered
- **THEN** ingestion is blocked with a structured unknown-importer error and no partial workload package is handed to Step2
