## ADDED Requirements

### Requirement: DFT/QE workflow declares SCF coverage as adapter coverage
The DFT/QE adapter SHALL declare its canonical SCF phase coverage as adapter-required coverage. This coverage SHALL include the operation phases needed for the selected full SCF shell or explicitly declare unavailable/reduced phases when the package is not full-workload eligible. The generic core SHALL treat this as adapter metadata, not as a global requirement for other workload families.

#### Scenario: QE full workflow keeps strict SCF phases
- **WHEN** the DFT/QE adapter emits a full SCF WorkloadPackage
- **THEN** the workflow requires timing evidence for the adapter-declared SCF phases and blocks trusted QE full-workload claims if any required phase is missing

#### Scenario: Non-QE workflow does not inherit QE phases
- **WHEN** the selected workload adapter is not `dft_qe`
- **THEN** final coverage validation does not require `h_psi`, `s_psi`, `diagonalize`, or any other QE-specific node unless that adapter explicitly declares them
