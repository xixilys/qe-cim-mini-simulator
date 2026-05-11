## ADDED Requirements

### Requirement: Backend evidence uses adapter coverage for all workload families
Generic simulation backends SHALL emit timing events, summaries, or equivalent coverage artifacts for the required coverage declared by the selected WorkloadPackage workflow. DFT/QE SCF phases SHALL be used only for the DFT/QE adapter workflow; other workloads SHALL use their own coverage declaration or lowered executable graph nodes.

#### Scenario: Non-QE full-flow simulation passes coverage
- **WHEN** a non-QE workload runs through standalone SystemC or gem5+SystemC and every adapter-required coverage item appears in events, summaries, or equivalent backend evidence
- **THEN** phase coverage passes without requiring QE phase names

#### Scenario: Backend does not support lowered construct
- **WHEN** a workload contains a lowered loop, streaming recurrence, dynamic region, or state construct that the backend cannot execute or summarize
- **THEN** the backend returns a structured unsupported result and the final report blocks trusted full-workload claims

### Requirement: Backend request preserves workload-family provenance
The simulation request SHALL preserve workload id, adapter id/version where available, source graph id, executable graph id, graph-lowering status, required coverage, and source-to-executable mapping. This provenance SHALL be sufficient to replay and audit which family workflow was simulated.

#### Scenario: Request includes lowering and coverage provenance
- **WHEN** the Python bridge submits a lowered graph to the generic backend
- **THEN** the request includes graph-lowering metadata and required coverage or a resolvable reference to it for evidence validation
