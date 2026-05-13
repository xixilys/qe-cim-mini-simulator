# step3-simulation-evidence-workflow Specification

## Purpose
Define the Step3 simulation and evidence workflow contract that governs how the DSE pipeline consumes persisted Step2 handoff artifacts, validates the handoff before launching high-fidelity simulation, reconstructs replayable simulation requests, emits full-flow evidence and structured status artifacts, and rejects diagnostic or untrusted paths. Step3 SHALL be the gateway for trusted full-flow evidence.
## Requirements
### Requirement: Step3 consumes persisted Step2 handoff artifacts
Step3 SHALL begin from a Step2 run directory and SHALL consume persisted artifacts including `step2_status.json`, `step2_artifact_validation.json`, `workload_package.json`, `workload_graph.json`, `graph_lowering_report.json`, `executable_graph.json`, `architecture_catalog.json`, `architecture.json`, `design_point.json`, `mapping.json`, `mapping_promotion_decision.json`, `mapping_legality_matrix.json`, `mapping_seed_set.json`, `mapping_candidate_records.json`, `mapping_selected_record.json`, `mapping_simulation_samples.json`, `mapping_feedback_state.json`, and `convergence_status.json`. Hidden Python process state SHALL NOT be required to reconstruct the selected simulation request.

#### Scenario: Step2 artifacts are copied into Step3 evidence
- **WHEN** Step3 starts from a valid Step2 run directory
- **THEN** the Step3 run directory contains `step2_input/` copies of the available Step2 input artifacts and records those copies in Step3 status or evidence manifests

#### Scenario: Missing required Step2 artifact blocks simulation
- **WHEN** a required Step2 artifact such as `mapping_promotion_decision.json` or `design_point.json` is absent
- **THEN** Step3 writes `step3_status.json` with `status` `blocked_before_simulation`, records the missing artifact reason, and SHALL NOT write a successful simulation result

### Requirement: Step3 validates the handoff before launching high-fidelity simulation
Step3 SHALL validate Step2 promotion, dynamic artifact references, selected-mapping legality, graph-lowering status, full-workload eligibility, architecture binding eligibility, and workload claim boundary before invoking SystemC or gem5+SystemC. Invalid handoffs SHALL be blocked before backend execution.

#### Scenario: Unsupported lowering is blocked before backend execution
- **WHEN** `graph_lowering_report.json` is unsupported, reduced, or not full-workload eligible
- **THEN** Step3 records an unsupported-or-reduced-lowering reason and does not attempt trusted simulation

#### Scenario: Illegal selected mapping is blocked before backend execution
- **WHEN** the selected mapping references missing resources, illegal placements, or recorded legality violations
- **THEN** Step3 records an illegal-selected-mapping reason and does not submit that mapping as trusted high-fidelity evidence

#### Scenario: Step2 final claim is rejected
- **WHEN** Step2 artifacts attempt to mark a candidate as a trusted final winner or trusted final claim before Step3 evidence exists
- **THEN** Step3 rejects the handoff and records that Step2 cannot create final trusted conclusions

### Requirement: Step3 rejects diagnostic, smoke, prototype, predicted-only, and candidate-only paths
Step3 SHALL NOT treat smoke, diagnostic-only, synthetic/reduced, trace-only, fixed-timing, driver hello, prototype, stub, missing-binding, predicted-only, or candidate-only paths as trusted full-flow evidence. These paths MAY be recorded as diagnostics or limitations, but SHALL fail trusted final gates.

#### Scenario: Smoke claim boundary cannot pass Step3
- **WHEN** the workload package or Step2 handoff has a smoke or diagnostic claim boundary
- **THEN** Step3 records a diagnostic-claim-boundary reason and `trusted_for_final_ranking` is false

#### Scenario: Missing simulation binding remains candidate-only
- **WHEN** Step2 selects an architecture or mapping without trusted SystemC or gem5+SystemC binding coverage
- **THEN** Step3 blocks or downgrades the attempt and SHALL NOT emit a trusted final ranking sample

### Requirement: Step3 reconstructs a replayable simulation request from disk
Step3 SHALL rebuild the backend request using persisted workload package, executable graph, architecture, DesignPoint, selected mapping, scheduling/output configuration, and Step2 promotion metadata. The request SHALL include enough provenance to show that Step2 handoff artifacts were present and used.

#### Scenario: Valid handoff produces simulation_request
- **WHEN** Step3 receives a valid promoted Step2 handoff and the configured backend executable is available
- **THEN** it writes `simulation_request.json` containing workload nodes, edges, architecture resources, mapping, scheduling/output fields, and Step2 handoff provenance

#### Scenario: Non-QE request remains domain-neutral
- **WHEN** Step3 runs a sparse, ML/tensor, stencil, graph analytics, database/vector-search, or custom non-QE workload
- **THEN** the request and final report do not require QE-only fields such as `npw`, `nkb`, `h_psi`, `s_psi`, `diagonalize`, `mix_rho`, or `veff`

#### Scenario: DFT/QE request preserves profile/importer boundary
- **WHEN** Step3 runs the DFT/QE reference profile/importer workflow
- **THEN** QE-specific coverage appears only as profile/workflow metadata and does not become a required global field for other workload families

### Requirement: Step3 emits full-flow evidence and structured status artifacts
A Step3 run SHALL write `step3_status.json` for every attempt. A completed simulation attempt SHALL emit `simulation_request.json`, `simulation_result.json`, `numerical_validation.json`, `verdict.json`, `evidence_requirements.json`, `claim_validation.json`, `final_report.json`, `final_report.md`, `artifact_manifest.json`, and `manifest.json` or explicit unavailable/blocker reasons. Trusted status SHALL derive from the full-flow evidence gates, not from simulator exit code alone.

#### Scenario: Trusted full-flow evidence is emitted
- **WHEN** simulation completes and all evidence, verdict, and claim-validation gates pass
- **THEN** Step3 writes `status` `trusted_full_flow_evidence_emitted` and `trusted_for_final_ranking` true

#### Scenario: Successful simulation with evidence gaps remains untrusted
- **WHEN** the simulator exits successfully but required evidence, coverage, claim validation, or replay artifacts are missing
- **THEN** Step3 writes `status` `simulation_completed_untrusted` and lists evidence-gap reasons

#### Scenario: Simulator unavailable is a structured blocker
- **WHEN** the configured SystemC or gem5+SystemC executable is unavailable
- **THEN** Step3 writes `status` `blocked_simulator_unavailable`, preserves available Step2 inputs, and SHALL NOT synthesize a successful result

### Requirement: Step3 cross-step validation covers generic and profile/importer-specific workflows
Step3 implementation validation SHALL include tests that start from Step1 workload/package generation, run Step2 artifact emission, and then run Step3 simulation/evidence or blocked-handoff checks. Tests SHALL cover representative non-QE workloads and DFT/QE reference profile/importer regression.

#### Scenario: Generic sparse workflow passes without QE assumptions
- **WHEN** a sparse linear-algebra workload runs through Step1, Step2, and Step3
- **THEN** Step3 emits trusted full-flow evidence and the request/report contain generic sparse coverage rather than QE-only phase requirements

#### Scenario: Database vector-search workflow passes without QE assumptions
- **WHEN** a database/vector-search workload runs through Step1, Step2, and Step3
- **THEN** Step3 emits trusted full-flow evidence and no QE-only required phases are introduced

#### Scenario: DFT/QE regression keeps profile-scoped seeds and coverage
- **WHEN** a DFT/QE workload runs through Step1, Step2, and Step3
- **THEN** DFT/QE seed policies and required coverage remain profile-scoped and do not rename or expose old QE-domain global defaults

### Requirement: Step3 artifact writes are atomic and concurrency-safe
Step3 SHALL ensure that simulation results, evidence artifacts, and status files are written atomically and are safe under concurrent execution. Concurrent Step3 runs SHALL NOT corrupt shared artifacts or leave partial results visible to downstream stages.

#### Scenario: Concurrent Step3 runs use unique directories
- **WHEN** two Step3 runs execute concurrently from the same Step2 handoff
- **THEN** each run writes to a distinct `run_id` directory and neither overwrites the other's artifacts

#### Scenario: Partial simulation result is quarantined
- **WHEN** a Step3 run crashes after writing `simulation_result.json` but before completing `step3_status.json`
- **THEN** the incomplete run directory is not visible to final report generation as trusted evidence

#### Scenario: Concurrent evidence append is atomic
- **WHEN** multiple Step3 runs append evidence to a shared evidence manifest
- **THEN** each append is atomic and no evidence records are lost or interleaved

### Requirement: Step3 evidence is broad-workload aware
Step3 SHALL reconstruct simulation requests, evidence requirements, verdicts, claim validation, and final reports from generic Step2 artifacts for every supported workload family. Step3 SHALL apply profile/importer-specific coverage only when it is declared by the selected workload package or workflow metadata.

#### Scenario: Non-QE Step3 request has no QE required fields
- **WHEN** Step3 reconstructs a simulation request for an ML/tensor, sparse, stencil, graph analytics, database/vector-search, or custom workload
- **THEN** the request is valid without QE-only fields such as `npw`, `nkb`, `h_psi`, `s_psi`, `mix_rho`, or `veff`

#### Scenario: Profile/importer validation controls domain claims
- **WHEN** Step3 has complete generic simulation evidence but missing profile/importer-domain validation for a workload family
- **THEN** trusted timing/resource claims may pass while domain correctness claims remain blocked or unavailable

