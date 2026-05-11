## ADDED Requirements

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
- **THEN** L3 results show explainable differences in latency, throughput, power, or data movement rather than identical fixed-stub outputs

#### Scenario: L3 request includes workload dependencies
- **WHEN** a ComputeGraph contains DataEdges
- **THEN** the L3 request includes those edges and the backend uses them for execution ordering and data transfer modeling

### Requirement: L4 gem5 co-simulation is gated by full-system evidence
The L4 path SHALL be reported as complete only after gem5 GenericAccel can run a full QE-flow or equivalent end-to-end workload, read command descriptors or equivalent requests, model DMA/PIO completion, and exchange timing/results with the generic SystemC backend or declared substitute.

#### Scenario: Stub status is reported honestly
- **WHEN** GenericAccel only implements MMIO timed-stub behavior
- **THEN** DSE reports L4 as stub/prototype and does not use it as evidence for full-system timing claims

#### Scenario: L4 pilot proves co-simulation path
- **WHEN** a gem5+SystemC pilot executes a QE-flow workload through descriptor/request ingestion, SystemC timing execution, and completion
- **THEN** the validation evidence records the command, timing result, exported artifacts, and any remaining model limitations

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
L1 analytical, L2 TLM, and surrogate evaluators SHALL be used to reduce search cost, estimate uncertainty, and prioritize candidates for SystemC/gem5+SystemC simulation. They SHALL NOT select final winners without high-fidelity evidence.

#### Scenario: L1 screens large design space
- **WHEN** the design space is too large for exhaustive SystemC simulation
- **THEN** L1/L2 screening ranks or filters candidates and records predicted metrics plus uncertainty for promotion decisions

#### Scenario: Predicted winner requires simulation
- **WHEN** a candidate is predicted best by L1/L2 or a surrogate model
- **THEN** it must be promoted to SystemC or gem5+SystemC before it can be reported as the best architecture or mapping

### Requirement: High-fidelity results update screening models
The multi-fidelity evaluator SHALL feed SystemC/gem5+SystemC results back into ranking, calibration, and optional surrogate models so that later screening iterations learn from measured behavior.

#### Scenario: Surrogate calibration receives simulation sample
- **WHEN** a candidate has completed SystemC/gem5+SystemC simulation
- **THEN** its measured metrics are stored as calibration samples for subsequent candidate ranking or uncertainty estimation

#### Scenario: Misranked prediction changes future search
- **WHEN** high-fidelity simulation contradicts low-fidelity ranking for a candidate family
- **THEN** the search state records the misprediction and adjusts confidence, promotion policy, or surrogate parameters for related candidates
