# multi-fidelity-dse-evaluation Specification

## Purpose
Define the DSE evaluation contract for replayable DesignPoints, stable EvaluationResults, deterministic search-space generation, multi-objective ranking, L1/L2/L3/L4 fidelity boundaries, evidence-driven promotion, feedback calibration, and honest reporting of gaps.
## Requirements
### Requirement: DesignPoint is the atomic candidate contract
A DesignPoint SHALL bind a SystemArchitecture, task mapping, scheduling policy, and configuration metadata under a stable design point id. Evaluators SHALL not mutate the input DesignPoint except through explicit derived artifacts.

#### Scenario: DesignPoint can be replayed
- **WHEN** a design point is selected from DSE results
- **THEN** its architecture, mapping, scheduling policy, and configuration are sufficient to rerun the evaluation deterministically under the same evaluator version

#### Scenario: Missing mapping is handled explicitly
- **WHEN** a design point omits a mapping for a required task
- **THEN** the evaluator marks the point infeasible or invokes a declared mapper rather than silently assigning a default accelerator

### Requirement: EvaluationResult is a typed, stable result contract
EvaluationResult SHALL expose latency, throughput, power, energy, area, efficiency, communication, feasibility, violation reasons, fidelity level, provenance, and optional timeline/uncertainty fields. Public evaluator APIs SHALL return this contract or a documented compatible wrapper.

#### Scenario: Evaluator return type is stable
- **WHEN** DSEOrchestrator invokes an evaluator
- **THEN** the returned value supports the EvaluationResult fields used by ranking, reporting, and tests

#### Scenario: Infeasible result still contains diagnostics
- **WHEN** evaluation fails due to unsupported mapping or resource violation
- **THEN** EvaluationResult sets `feasible` to false and includes violation reasons without crashing the full DSE run

### Requirement: SearchSpace generation is deterministic and constraint-aware
SearchSpace SHALL generate design points from declared parameter dimensions, constraints, and pruning rules. Generation SHALL be reproducible for a fixed seed and SHALL report the nominal and feasible design-space sizes.

#### Scenario: Fixed seed reproduces candidate order
- **WHEN** SearchSpace generation runs twice with the same dimensions, constraints, and seed
- **THEN** the same ordered design point ids are produced

#### Scenario: Constraint pruning is counted
- **WHEN** constraints remove illegal parameter combinations
- **THEN** DSE reports both the original candidate count and the remaining feasible/generated count

### Requirement: DSEOrchestrator supports multi-objective ranking and Pareto analysis
DSEOrchestrator SHALL evaluate candidate design points, retain infeasible diagnostics, compute Pareto frontiers over declared objectives, and expose best-design queries for single-objective views.

#### Scenario: Pareto frontier excludes dominated points
- **WHEN** two feasible results are compared on latency, power, and area and one is no worse on all objectives and better on at least one
- **THEN** the dominated result is excluded from the Pareto frontier

#### Scenario: Objective direction is explicit
- **WHEN** a metric is used for ranking
- **THEN** the DSE configuration declares whether it is minimized, maximized, or constrained

### Requirement: L1 analytical evaluator models roofline, scheduling, and communication
The L1 evaluator SHALL estimate latency using compute roofline limits, memory bandwidth limits, operator efficiency, task dependencies, parallel scheduling, and data movement costs. It SHALL expose enough diagnostics to identify compute-bound versus memory-bound tasks.

#### Scenario: Compute-bound task uses peak compute limit
- **WHEN** a task's operational intensity is high relative to memory bandwidth
- **THEN** L1 latency is dominated by effective compute throughput for the mapped accelerator

#### Scenario: Parallel independent tasks overlap
- **WHEN** two tasks have no dependency and are placed on different available accelerators
- **THEN** L1 scheduling permits overlap and reports a makespan shorter than strict serial execution when resources allow

### Requirement: L2 evaluator provides transaction-level refinement
The L2 evaluator SHALL refine L1 estimates with transaction-level communication, queueing, and coarse runtime orchestration effects while preserving the EvaluationResult contract.

#### Scenario: L2 consumes L1-compatible design point
- **WHEN** a design point that passed IR and architecture validation is evaluated at L2
- **THEN** L2 accepts the same DesignPoint and ComputeGraph inputs without requiring QE-specific fields

#### Scenario: L2 exposes refinement provenance
- **WHEN** L2 changes latency or communication estimates relative to L1
- **THEN** the result records fidelity `L2` and includes provenance sufficient to explain the refinement source

### Requirement: L3 standalone simulation consumes architecture and mapping differences
The L3 evaluator SHALL invoke the generic simulation backend and SHALL consume accelerator capabilities, workload edges, operator models, interconnect, and task mapping such that materially different architectures can produce materially different results.

#### Scenario: GPU FPGA CIM probe differs
- **WHEN** the same workload is mapped separately to GPU, FPGA, and CIM descriptors with different capabilities
- **THEN** L3 results show explainable differences in latency, throughput, power, or data movement rather than identical fixed-output diagnostics

#### Scenario: L3 request includes workload dependencies
- **WHEN** a ComputeGraph contains DataEdges
- **THEN** the L3 request includes those edges and the backend uses them for execution ordering and data transfer modeling

#### Scenario: L3 request carries graph lowering provenance
- **WHEN** the source workload graph includes loops, hierarchy, streaming feedback, stateful edges, or dynamic control
- **THEN** the L3 request cites the graph lowering report and either carries a supported executable view or fails before simulation with an unsupported-graph diagnostic

### Requirement: L4 gem5 co-simulation is gated by full-system evidence
The L4 path SHALL be reported as complete only after gem5 GenericAccel can run the selected full WorkloadPackage or a declared equivalent end-to-end workload, read command descriptors or equivalent requests, model DMA/PIO completion, and exchange timing/results with the generic SystemC backend or declared substitute.

#### Scenario: Missing L4 proof is reported honestly
- **WHEN** a gem5+SystemC attempt lacks a passing `gem5_l4_proof.json`
- **THEN** DSE reports L4 as untrusted for that sample and does not use it as evidence for full-system timing claims

#### Scenario: Missing real L4 flag blocks synthetic evidence
- **WHEN** `gem5_systemc` is requested without the real L4 harness flag
- **THEN** the workflow fails explicitly and does not create synthetic `verdict.json` or `simulation_result.json` artifacts

- **WHEN** a gem5+SystemC pilot executes a full workload package through descriptor/request ingestion, SystemC timing execution, and completion
- **THEN** the validation evidence records the command, timing result, exported artifacts, and any remaining model limitations

#### Scenario: Passing L4 proof is bounded to transport and timing replay
- **WHEN** `gem5_l4_proof.json` passes for a generic heterogeneous backend run
- **THEN** the sample may be trusted for descriptor/request/SystemC/completion transport and timing-result replay
- **AND** it SHALL NOT imply QE FP64 physics correctness, board correctness, RTL correctness, or comparative best-architecture claims without separate evidence

### Requirement: Promotion policy is explicit, budgeted, and evidence-driven
MultiFidelityEvaluator SHALL define when to promote from L1 to L2 and from L2 to L3/L4 using confidence, uncertainty, resource margins, Pareto-front proximity, workload family, and simulation budget constraints.

#### Scenario: Low-confidence L1 promotes
- **WHEN** L1 confidence is below the configured threshold and promotion budget remains
- **THEN** the evaluator promotes the design point to L2 and records the promotion reason

#### Scenario: Budget exhaustion is visible
- **WHEN** promotion would be beneficial but the configured budget is exhausted
- **THEN** the result remains at the current fidelity and records a budget-exhausted reason

### Requirement: Metrics are unit-consistent across fidelity levels
All fidelity levels SHALL report latency in milliseconds, throughput in GOPS or declared units, power in watts, energy in joules, area in mm², data movement in bytes/MB with clear conversion, and utilization as bounded ratios or percentages.

#### Scenario: Cross-fidelity metrics can be compared
- **WHEN** the same design point is evaluated at L1 and L3
- **THEN** common metric fields use the same units and can be compared without ad-hoc conversions

#### Scenario: Unit mismatch fails validation
- **WHEN** an evaluator produces a metric in an unexpected unit without metadata
- **THEN** result validation fails before the metric is used for ranking

### Requirement: DSE reports evidence quality and known gaps
Every DSE run report SHALL include evaluator versions, input workload identity, design-space size, feasibility statistics, validation commands or gaps, and known incomplete backend paths.

#### Scenario: Report includes reproducibility block
- **WHEN** a DSE run completes
- **THEN** the report includes commands, seeds, code paths, workload identifiers, and backend versions needed to reproduce the run

#### Scenario: Known backend gap is not hidden
- **WHEN** a selected design relies on a backend with known stub or unvalidated behavior
- **THEN** the report highlights that gap and downgrades claim confidence accordingly

### Requirement: Low-fidelity evaluators are candidate generators, not final arbiters
L1 analytical, L2 TLM, and surrogate evaluators SHALL be used to reduce search cost, estimate uncertainty, and prioritize candidates for SystemC/gem5+SystemC simulation. They SHALL NOT select final winners without high-fidelity evidence. The system SHALL enforce this rule through the TrustGate; no evaluator SHALL bypass the TrustGate.

#### Scenario: L1 screens large design space
- **WHEN** the design space is too large for exhaustive SystemC simulation
- **THEN** L1/L2 screening ranks or filters candidates and records predicted metrics plus uncertainty for promotion decisions

#### Scenario: Predicted winner requires simulation
- **WHEN** a candidate is predicted best by L1/L2 or a surrogate model
- **THEN** it must be promoted to SystemC or gem5+SystemC before it can be reported as the best architecture or mapping

#### Scenario: L1/L2 candidate is blocked by TrustGate
- **WHEN** an L1-only or L2-only candidate is submitted to the TrustGate
- **THEN** the TrustGate rejects the candidate with `reason_id="l1_only_evidence"` or `reason_id="l2_only_evidence"` and prevents it from entering trusted ranking

#### Scenario: Orchestrator cannot bypass TrustGate for L1/L2
- **WHEN** `DSEOrchestrator.get_best_design()` is called and the best candidate has only L1/L2 evidence
- **THEN** the orchestrator returns `no_trusted_candidate` or promotes the candidate to L3/L4 instead of returning the L1/L2 candidate as best

### Requirement: High-fidelity results update screening models
The multi-fidelity evaluator SHALL feed SystemC/gem5+SystemC results back into ranking, calibration, and optional surrogate models so that later screening iterations learn from measured behavior.

#### Scenario: Surrogate calibration receives simulation sample
- **WHEN** a candidate has completed SystemC/gem5+SystemC simulation
- **THEN** its measured metrics are stored as calibration samples for subsequent candidate ranking or uncertainty estimation

#### Scenario: Misranked prediction changes future search
- **WHEN** high-fidelity simulation contradicts low-fidelity ranking for a candidate family
- **THEN** the search state records the misprediction and adjusts confidence, promotion policy, or surrogate parameters for related candidates

### Requirement: High-fidelity feedback samples are multi-candidate artifacts
The multi-fidelity evaluator SHALL persist every promoted high-fidelity attempt in `mapping_simulation_samples.json`. Each sample SHALL include candidate id, backend, fidelity level, lifecycle status, `trusted_final_eligible`, metrics when available, evidence ids, and any blocker or missing-proof reason.

#### Scenario: Multiple promoted samples are recorded
- **WHEN** a DSE run promotes more than one architecture or mapping candidate to SystemC or gem5+SystemC
- **THEN** `mapping_simulation_samples.json` contains one sample record for each attempted promoted candidate with its metrics, trust label, and evidence ids

#### Scenario: Blocked high-fidelity attempt remains diagnostic
- **WHEN** a promoted gem5+SystemC or SystemC attempt fails, times out, lacks proof, or is otherwise untrusted
- **THEN** the sample is retained with `trusted_final_eligible` false and a blocker or missing-proof reason instead of being used in trusted ranking

### Requirement: Feedback state records ranking correction and simulation budget
The feedback loop SHALL persist `mapping_feedback_state.json` with screened, promoted, attempted, completed, trusted, blocked, and remaining sample counts. The state SHALL record how high-fidelity measurements changed ranking, calibration, pruning, promotion policy, or next-candidate selection.

#### Scenario: Trusted sample updates ranking state
- **WHEN** a SystemC or gem5+SystemC sample passes all trust gates
- **THEN** `mapping_feedback_state.json` records the sample as trusted feedback and records the ranking or calibration effect applied to later candidate selection

#### Scenario: Promotion budget exhaustion is explicit
- **WHEN** promoted candidates remain but the configured SystemC/gem5+SystemC budget is consumed
- **THEN** `mapping_feedback_state.json` records budget exhaustion and lists the unattempted or predicted-only candidates separately from trusted samples

### Requirement: Convergence status is machine-checkable
The evaluator SHALL emit `convergence_status.json` for feedback-loop runs. The artifact SHALL record configured criteria, thresholds, evaluated metric history, stop reason, convergence boolean, budget status, and limitations. Budget exhaustion SHALL NOT be reported as full convergence unless a configured convergence criterion also passed.

#### Scenario: Frontier or top-K stability stops the loop
- **WHEN** the configured trusted frontier or top-K stability criterion is satisfied across feedback iterations
- **THEN** `convergence_status.json` records `stop_reason` as convergence and includes the evidence-backed metric history used for the decision

#### Scenario: Budget exhaustion is not convergence
- **WHEN** simulation budget is exhausted before stability, improvement, uncertainty, or family-coverage criteria pass
- **THEN** `convergence_status.json` records budget exhaustion, `converged` false, and a limitation explaining that global optimality is not proven

### Requirement: Comparative ranking uses trusted samples only
Comparative architecture, mapping, and Pareto ranking SHALL use only candidates with trusted full-flow SystemC or gem5+SystemC samples and resolved evidence ids. Predicted-only, blocked, untrusted, smoke-only, or diagnostic-only candidates MAY appear in appendices but SHALL NOT become trusted winners or Pareto members.

#### Scenario: Smoke samples remain diagnostic
- **WHEN** a candidate has smoke-only or bring-up-only evidence
- **THEN** it is retained only as diagnostic context and is rejected by the final trusted ranking check

#### Scenario: Predicted candidate is excluded from trusted Pareto set
- **WHEN** a candidate has only L1/L2/surrogate screening results and no trusted high-fidelity sample
- **THEN** it is excluded from trusted Pareto and winner claims and appears only as predicted-only or candidate-only evidence

#### Scenario: Trusted comparison cites every compared sample
- **WHEN** the final report compares two candidates on latency, power, energy, data movement, or Pareto dominance
- **THEN** every compared candidate links to its trusted sample evidence and unresolved evidence ids fail claim validation

### Requirement: Single trusted sample cannot claim best architecture
A single trusted high-fidelity sample SHALL NOT be sufficient to claim best architecture, best mapping, or trusted Pareto frontier. Feasibility claims are permitted; comparative winner claims require multiple trusted samples or explicit convergence evidence.

#### Scenario: Single sample claims feasibility only
- **WHEN** exactly one candidate has trusted high-fidelity evidence
- **THEN** the TrustGate permits `trusted_feasibility=true` but sets `trusted_comparative_ranking=false`

#### Scenario: Single sample cannot claim winner
- **WHEN** a report attempts to select a best architecture with only one trusted sample
- **THEN** the TrustGate blocks the winner claim with `reason_id="insufficient_comparative_evidence"` and requires at least two trusted samples or convergence artifacts

#### Scenario: Multiple samples enable comparative ranking
- **WHEN** two or more candidates have trusted high-fidelity evidence with comparable configurations
- **THEN** the TrustGate permits comparative ranking and Pareto analysis across those candidates

#### Scenario: Convergence evidence substitutes for multiple samples
- **WHEN** a feedback-loop run produces `convergence_status.json` with `converged=true` and frontier stability evidence
- **THEN** the TrustGate may permit winner claims even with few samples, provided the convergence artifact supports the claim

### Requirement: Gem5 SystemC samples require passing L4 proof for trusted eligibility
The multi-fidelity evaluator SHALL keep `backend="gem5_systemc"` samples untrusted unless the sample includes a passing `gem5_l4_proof.json` artifact. Passing proof MAY make the sample eligible for trusted L4 transport/timing replay claims subject to the TrustGate.

#### Scenario: Passing proof promotes gem5 sample to trusted L4 eligibility
- **WHEN** a promoted `gem5_systemc` sample includes a passing `gem5_l4_proof.json`
- **THEN** `mapping_simulation_samples.json` records the sample with `trusted_final_eligible=true` for bounded L4 transport/timing replay
- **AND** the sample evidence ids include `gem5_l4_proof.json`

#### Scenario: Missing proof keeps gem5 sample diagnostic
- **WHEN** a promoted `gem5_systemc` sample lacks a passing `gem5_l4_proof.json`
- **THEN** `mapping_simulation_samples.json` records `trusted_final_eligible=false` with a missing or failed proof blocker

### Requirement: L3 SystemC trust remains independent of L4 availability
The multi-fidelity evaluator SHALL continue to allow trusted standalone SystemC L3 samples when their full-flow SystemC evidence passes, even if real gem5 L4 execution is unavailable or blocked.

#### Scenario: L3 full-flow remains trusted when L4 is not run
- **WHEN** a standalone SystemC full-flow sample passes its evidence checks and gem5+SystemC is not run
- **THEN** the sample may remain trusted L3 evidence and the run records L4 as not run rather than failed

