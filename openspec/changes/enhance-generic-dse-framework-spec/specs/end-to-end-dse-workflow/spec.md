## ADDED Requirements

### Requirement: End-to-end DSE run is the top-level completion unit
The system SHALL define a complete DSE run as the execution of workload ingestion, architecture instantiation, mapping search, simulation, evidence export, and final analysis report generation. A run SHALL NOT be considered complete if it only produces intermediate candidates or analytical predictions.

#### Scenario: Complete run produces final report
- **WHEN** the user launches a full DSE run for a supported workload family and architecture catalog
- **THEN** the system produces a final analysis report, ranked design points, selected mapping decisions, and evidence artifacts for every final claim

#### Scenario: Partial run is labeled non-final
- **WHEN** a run stops after L1/L2 screening or before SystemC/gem5+SystemC evidence is produced for finalists
- **THEN** the run status is labeled partial or predicted-only and cannot be used as a final DSE conclusion

### Requirement: Pipeline stages have explicit inputs and outputs
The end-to-end workflow SHALL define stable stage boundaries for workload ingestion, design-space generation, mapping search, simulation scheduling, evidence collection, result aggregation, and report generation. Each stage SHALL persist enough artifacts for replay or debugging.

#### Scenario: Stage output feeds next stage
- **WHEN** workload ingestion completes
- **THEN** it emits a workload graph artifact consumed by architecture/mapping stages without hidden in-memory-only state

#### Scenario: Failed stage preserves diagnostics
- **WHEN** any pipeline stage fails
- **THEN** the run directory contains the stage name, input artifact ids, error message, and partial outputs needed for debugging

### Requirement: Architecture catalog is extensible and binding-aware
The system SHALL support an extensible architecture catalog with architecture families, parameterized instances, component registries, constraints, and SystemC/gem5 binding metadata. Architectures without simulation binding SHALL be allowed as candidates but SHALL NOT produce final trusted conclusions.

#### Scenario: New architecture family can be added
- **WHEN** a developer adds a new architecture family with valid schema, constraints, and optional simulation binding
- **THEN** the DSE generator can instantiate it without changing core mapping or reporting code

#### Scenario: Unbound architecture is candidate-only
- **WHEN** an architecture instance lacks a valid SystemC or gem5+SystemC binding
- **THEN** the workflow may screen it analytically but labels it ineligible for final trusted ranking

### Requirement: Mapping search is algorithmic and constraint-aware
The system SHALL search mapping choices algorithmically using legality matrices, seeded domain mappings, pruning, local or beam search, and SystemC-gated finalist evaluation. Manual fixed mappings MAY be used as baselines but SHALL NOT be the only mapping strategy.

#### Scenario: Legality matrix filters invalid placements
- **WHEN** a workload operator is unsupported by a hardware resource or violates memory/precision constraints
- **THEN** mapping search excludes that placement or records it as illegal before simulation

#### Scenario: Search proposes improved mappings
- **WHEN** the mapping optimizer evaluates candidate mappings under the same architecture and workload
- **THEN** it can produce ranked alternatives with differences in latency, data movement, utilization, or constraint satisfaction

### Requirement: Final candidates are SystemC-gated
Every design point or mapping included in the final trusted ranking SHALL have SystemC or gem5+SystemC evidence. L1/L2 analytical/TLM results SHALL be used only for screening, prioritization, or explanation unless explicitly labeled predicted-only.

#### Scenario: Final ranking has SystemC evidence
- **WHEN** the final report ranks top-K design points or mappings
- **THEN** each ranked item links to SystemC or gem5+SystemC result files and run ids

#### Scenario: Analytical-only candidate is excluded from trusted ranking
- **WHEN** a candidate has only L1/L2 evaluation results
- **THEN** it may appear in an appendix or candidate list but not in the trusted final ranking

### Requirement: Evidence artifacts are exported for user inspection
Each SystemC or gem5+SystemC run used for decisions SHALL produce a run directory containing manifest, design point, architecture, mapping, workload graph, simulation request, simulation result, logs, summary traces, and verdict. Debug and forensic artifacts SHALL be generated for finalists, failures, or user-selected runs.

#### Scenario: Summary evidence exists for every trusted run
- **WHEN** a SystemC run contributes to a final conclusion
- **THEN** its run directory contains `manifest.json`, `design_point.json`, `architecture.json`, `mapping.json`, `workload_graph.json`, `simulation_request.json`, `simulation_result.json`, logs, and verdict files

#### Scenario: Debug evidence is generated for finalist
- **WHEN** a design point is selected as finalist or exhibits anomalous behavior
- **THEN** the workflow exports event timeline, resource utilization, data movement, buffer/DMA/interconnect or equivalent debug traces when supported by the binding

### Requirement: Final analysis report links every claim to evidence
The final report SHALL express conclusions as claims with evidence ids, source files, metric values, confidence labels, and known limitations. Claims without required evidence SHALL be labeled untrusted, predicted, or blocked.

#### Scenario: Mapping comparison claim cites both runs
- **WHEN** the report states that mapping A outperforms mapping B
- **THEN** the claim links to SystemC evidence for both mappings under the same workload and comparable simulation configuration

#### Scenario: Bottleneck claim cites trace files
- **WHEN** the report claims a bottleneck is memory bandwidth, DMA, interconnect, buffer pressure, or compute utilization
- **THEN** the claim links to the trace or resource artifact supporting that bottleneck diagnosis

### Requirement: Run artifacts support replay and audit
The workflow SHALL generate replay metadata including command line, configuration, random seed, code revision where available, simulator version, environment summary, and artifact manifest. The user SHALL be able to locate and retrieve every output file referenced by the final report.

#### Scenario: Replay command is available
- **WHEN** a final SystemC/gem5+SystemC run completes
- **THEN** the run artifact set includes a replay command or equivalent config bundle sufficient to rerun the same design point

#### Scenario: Report references valid files
- **WHEN** the final report references an evidence file path
- **THEN** that path exists in the exported artifact directory or is marked as intentionally unavailable with a reason

### Requirement: Final analysis includes design recommendation and limitations
The final analysis SHALL identify the recommended architecture/mapping, explain why it wins, list Pareto alternatives, summarize phase breakdown, data movement, resource utilization, power/energy where available, and state limitations or unverified assumptions.

#### Scenario: Recommendation is explainable
- **WHEN** the workflow selects a best design point
- **THEN** the report explains the selected architecture, mapping, schedule/data-placement assumptions, key metrics, and evidence ids supporting the choice

#### Scenario: Limitations are explicit
- **WHEN** a metric, architecture binding, workload feature, or gem5/SystemC path is incomplete or unverified
- **THEN** the final report lists that limitation and prevents overclaiming beyond available evidence

### Requirement: Screening and simulation form a feedback optimization loop
The workflow SHALL use fast screening models to propose promising architecture and mapping candidates, then use gem5+SystemC or SystemC simulation results to update candidate ranking, search state, pruning decisions, and subsequent candidate generation. The best architecture SHALL be selected from simulation-backed feedback, not from initial screening alone.

#### Scenario: Screening proposes candidate architectures
- **WHEN** the DSE run begins with a large architecture and mapping space
- **THEN** analytical/TLM/surrogate screening produces a bounded candidate set with predicted metrics, uncertainty, and reasons for selection

#### Scenario: Simulation feedback updates search
- **WHEN** gem5+SystemC or SystemC evidence is produced for candidate architectures
- **THEN** the optimizer records the measured metrics and updates ranking, surrogate state, pruning thresholds, or next candidate selection based on that feedback

#### Scenario: Best architecture is simulation-backed
- **WHEN** the workflow reports the best architecture design
- **THEN** the selected design has direct SystemC or gem5+SystemC evidence and is not selected solely from initial screening predictions

### Requirement: Candidate states are tracked across screening and feedback
Each architecture/mapping candidate SHALL have an explicit lifecycle state such as generated, screened, promoted, simulated, rejected, finalist, or selected. State transitions SHALL record the reason, metric basis, and evidence id when available.

#### Scenario: Candidate promoted from screening
- **WHEN** a screened candidate is selected for high-fidelity simulation
- **THEN** its state changes to promoted with a reason such as Pareto-near, high uncertainty, domain seed, or exploration quota

#### Scenario: Candidate rejected after simulation
- **WHEN** simulation evidence shows a candidate is infeasible, dominated, or violates constraints
- **THEN** its state changes to rejected with the simulation evidence id and violation or dominance reason

### Requirement: Feedback loop stops by explicit convergence criteria
The DSE feedback loop SHALL stop only when configured convergence criteria are met, simulation budget is exhausted, or a blocking error occurs. Convergence criteria SHALL include frontier stability, no significant improvement, uncertainty reduction, or top-K stability as appropriate for the run.

#### Scenario: Frontier stability stops search
- **WHEN** consecutive feedback iterations produce no significant improvement in the trusted SystemC-backed Pareto frontier
- **THEN** the workflow may stop and produce the final analysis report with the convergence reason

#### Scenario: Budget exhaustion is reported
- **WHEN** the simulation budget is exhausted before convergence criteria are met
- **THEN** the final report states budget exhaustion and marks confidence according to available evidence

### Requirement: Architecture catalog schema separates family, instance, and simulation binding
The architecture catalog SHALL separate reusable architecture families from concrete architecture instances and from SystemC/gem5 simulation bindings. The catalog SHALL allow a family to be extended with new parameters, components, constraints, and bindings without changing the end-to-end workflow contract.

#### Scenario: Family instantiates concrete design point
- **WHEN** an architecture family receives a valid parameter assignment
- **THEN** the catalog emits a concrete architecture instance with components, memory hierarchy, interconnect, constraints, and binding eligibility metadata

#### Scenario: Binding metadata gates trusted eligibility
- **WHEN** an architecture instance lacks executable SystemC or gem5+SystemC binding metadata
- **THEN** the instance remains available for screening but is marked candidate-only for final reporting

#### Scenario: Initial catalog includes multiple extensible families
- **WHEN** the seed architecture catalog is loaded
- **THEN** it includes at least ten architecture families covering CPU-only baseline, Host+FPGA minimal, Host+FPGA+CIM, diag-heavy, streaming-heavy, memory-rich, low-power, balanced, debug, future-custom, and legacy reference classes

#### Scenario: Legacy four-cluster template is reference-only
- **WHEN** the historical four-cluster architecture appears in the catalog
- **THEN** it is labeled candidate-only or legacy/reference and is not the default or only architecture candidate

#### Scenario: Catalog validation gates trusted eligibility
- **WHEN** an architecture instance is marked trusted-final-eligible
- **THEN** validation checks duplicate ids, status labels, binding backend consistency, required operators, required communication routes, memory/power/area limits, and executable SystemC/gem5+SystemC binding coverage

### Requirement: Mapping search artifacts are persisted
The mapping optimizer SHALL persist the legality matrix, seed mappings, candidate mappings, search-state snapshots, promotion decisions, simulation samples, rejection reasons, and selected mapping record. These artifacts SHALL be linked from the run manifest.

#### Scenario: Legality matrix is inspectable
- **WHEN** mapping search filters placements before simulation
- **THEN** the persisted legality matrix records allowed and rejected node-resource pairs with reasons

#### Scenario: Selected mapping is reproducible
- **WHEN** the final report selects a mapping
- **THEN** the run artifacts include the selected mapping, search path or parent candidates, and simulation evidence that supports selection

### Requirement: Evidence modes define required artifact sets
The workflow SHALL support summary, debug, and forensic evidence modes with explicit required and optional artifacts. Summary mode SHALL be the minimum for trusted ranking; debug mode SHALL add timeline/resource/data-movement diagnostics; forensic mode SHALL add replay and waveform/full-trace artifacts where supported.

#### Scenario: Summary mode is sufficient for ranking claim
- **WHEN** a candidate is included in trusted ranking
- **THEN** summary evidence includes enough files to verify latency, phase breakdown, feasibility verdict, and referenced result metrics

#### Scenario: Forensic mode supports publication audit
- **WHEN** a candidate is selected for publication-level audit or user-requested deep inspection
- **THEN** forensic evidence includes replay metadata and full traces or explicitly records unsupported forensic outputs

### Requirement: Final report schema is machine-checkable
The final analysis report SHALL use a schema with sections for run metadata, workload, architecture catalog scope, search configuration, trusted ranking, predicted-only candidates, selected recommendation, Pareto alternatives, claim table, evidence index, limitations, and replay instructions.

#### Scenario: Report validator checks trusted claims
- **WHEN** a final report is generated
- **THEN** validation checks every trusted claim has an evidence id and every evidence id resolves to existing or explicitly unavailable artifact files

#### Scenario: Predicted-only candidates cannot appear as winners
- **WHEN** a candidate has no SystemC/gem5+SystemC evidence
- **THEN** report validation prevents it from being listed as selected best architecture or trusted Pareto point
