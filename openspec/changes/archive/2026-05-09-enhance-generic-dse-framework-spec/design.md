## Context

`docs/architecture/generic_dse_framework_design_spec_v1.md` describes a generic hardware/software co-design DSE framework for heterogeneous systems spanning CPU, GPU, FPGA, ASIC/CIM, SystemC, and gem5. The document captures the intended architecture and recent repair history, but it mixes four different concerns:

1. Long-lived architectural contracts.
2. Current prototype implementation details.
3. Known defects and code-review remediation notes.
4. Future roadmap items.

That mixture makes it hard to freeze requirements, prove implementation completeness, or distinguish a validated capability from a planned one. The OpenSpec change converts the design into a capability-oriented specification baseline with normative requirements, scenarios, risks, and validation hooks.

Current implementation anchors include:

- `dse_v2/core/ir/compute_graph.py`, `task_graph.py`, `execution.py`: application, task, and execution IR scaffolds.
- `dse_v2/core/architecture/accelerator.py`, `distributed.py`: accelerator/system/distributed descriptors.
- `dse_v2/dse/orchestrator.py`, `analytical_evaluator.py`, `tlm_evaluator.py`, `multi_fidelity.py`: search orchestration and multi-fidelity evaluation scaffolds.
- `dse_v2/backends/generic_systemc_bridge.py`: Python-to-C++ generic backend bridge.
- `model/generic_sim_backend/`: standalone C++ simulation backend and JSON request/result schemas.
- `gem5_integration/src/dev/generic_accel/`: GenericAccel MMIO timed-stub device model.
- `docs/overview/archive/docs/overview/archive/generic_dse_gem5_code_review_20260508.md`: reviewer findings that identify remaining blocking gaps.

Stakeholders:

- System architects need stable capability boundaries and non-goal boundaries.
- Framework developers need IR, API, schema, evaluator, and backend contracts.
- Accelerator modelers need self-description semantics for capabilities, resources, and limits.
- DSE researchers need reproducible metrics, promotion logic, Pareto semantics, and evidence quality.
- Reviewers need explicit implementation-status claims and validation criteria.

## Goals / Non-Goals

**Goals:**

- Produce OpenSpec-native capability specs for the generic DSE system.
- Convert the v1 design manual into testable normative requirements with scenarios.
- Separate stable architecture contracts from prototype/stub/planned implementation states.
- Define a professional spec structure suitable for design review, implementation planning, and later archival into `openspec/specs/`.
- Preserve the existing DFT/QE research context while making it a workload adapter, not a hard-coded framework assumption.
- Define validation evidence required before any capability is called complete.

**Non-Goals:**

- Do not implement code changes in this OpenSpec proposal step.
- Do not modify the protected upstream QE workspace outside `soft/qe-7.5/`.
- Do not claim L3/L4/gem5 full-system functionality as complete while current evidence indicates stub/prototype status.
- Do not freeze RTL, LCW binary encodings, exact buffer capacities, clock/reset/power closure, or final benchmark KPIs.
- Do not add new dependencies or replace the DSE algorithm stack as part of this spec-only change.

## Decisions

### Decision 1: Split the complex system into five capabilities

The system is specified as five OpenSpec capabilities:

1. `generic-dse-ir-contract`
2. `accelerator-system-description`
3. `multi-fidelity-dse-evaluation`
4. `generic-simulation-backend`
5. `dft-qe-workload-adapter`

**Rationale:** This split follows the system's natural dependency graph: workload/IR contracts feed architecture descriptors, which feed DSE evaluation, which may invoke generic simulation backends, with DFT/QE layered as a domain adapter. It avoids one monolithic spec that cannot be independently reviewed or tested.

**Rejected alternative:** A single `generic-dse-framework` capability. Rejected because it would hide interface boundaries and make archive-time requirement deltas too coarse.

### Decision 2: Treat status as part of the architecture contract

Each capability distinguishes:

- **Normative**: required behavior for completion.
- **Reference**: example values, templates, or supported initial presets.
- **Prototype/stub**: implemented scaffolds that must not be reported as complete behavior.
- **Planned**: out-of-scope roadmap work.

**Rationale:** The current design contains both completed scaffolds and known blockers. A professional spec must prevent over-claiming, especially for L3 backend differentiation and gem5 DMA/TLM behavior.

**Rejected alternative:** Keep status only in README/code-review notes. Rejected because reviewers and future implementers need status semantics in the spec itself.

### Decision 3: Use strict schema/version boundaries for IR and backend IPC

Compute graph, task graph, architecture descriptors, execution timeline, and simulation request/result objects are treated as versioned contracts. A backend may accept extensions but must preserve required fields, units, and failure semantics.

**Rationale:** The framework spans Python, C++, SystemC, and gem5. Versioned schemas reduce silent drift between `dse_v2` and `model/generic_sim_backend`.

**Rejected alternative:** Rely on ad-hoc Python dictionaries. Rejected because previous review identified return-type and parsing drift that broke integration.

### Decision 4: Define evaluator completion by evidence, not by code path existence

L1/L2/L3/L4 evaluators are considered complete only when their outputs satisfy metric contracts, architecture-difference probes, and validation tests. Existence of a bridge or executable is not sufficient.

**Rationale:** A backend can compile yet ignore accelerator capabilities or mapping differences. DSE ranking depends on evidence that the evaluator consumes the intended inputs.

**Rejected alternative:** Mark each evaluator complete when it runs without crashing. Rejected because it does not protect ranking correctness.

### Decision 5: Keep DFT/QE as a reference adapter over a generic core

The DFT/QE workload adapter defines canonical SCF nodes, tensor attributes, trace metadata, and calibration checks, but the generic framework remains operator-agnostic and accelerator-agnostic.

**Rationale:** The project priority remains DFT acceleration and algorithm freezing, but the new DSE framework is intended to be generic. This decision preserves both goals without embedding QE-specific assumptions into core IR and backend layers.

**Rejected alternative:** Make DFT/QE the primary IR shape. Rejected because it would undermine generic accelerator and workload exploration.

### Decision 6: Put implementation sequencing into tasks, not requirements

The spec files define what must be true. Implementation order, migration steps, and verification commands live in `tasks.md`.

**Rationale:** OpenSpec archives requirements into durable capability specs. Tasks are allowed to evolve as code state changes.

**Rejected alternative:** Encode file-by-file implementation steps inside requirements. Rejected because it would make requirements brittle and archive poorly.


### Decision 7: Make end-to-end execution the top-level acceptance gate

The system is not complete when individual IR, evaluator, or backend modules pass local tests. It is complete only when a full DSE run can ingest a workload, instantiate a rich architecture design point, search mappings, execute SystemC or gem5+SystemC simulations for final candidates, export evidence artifacts, and generate a final analysis report whose claims point to evidence ids.

**Rationale:** The user-facing value is the final architecture/mapping conclusion, not isolated model estimates. L1/L2 models can prune candidates, but final conclusions must be SystemC-gated and reproducible.

**Rejected alternative:** Treat SystemC as an optional validation pass after analytical DSE. Rejected because that allows untrusted predictions to appear as final design conclusions.


### Decision 8: Use screening only as a proposal mechanism and close the loop with simulation feedback

Fast analytical/TLM/surrogate models are required because the architecture and mapping space is too large for exhaustive gem5+SystemC simulation. However, they are candidate generators, not final arbiters. The optimizer must use high-fidelity simulation samples to update ranking, confidence, pruning, and subsequent candidate generation until convergence or budget exhaustion.

**Rationale:** This creates an actionable DSE loop: cheap models propose, SystemC/gem5+SystemC verifies, and measured evidence guides the next proposals. It prevents a one-shot analytical ranking from being mistaken for a trustworthy architecture recommendation.

**Rejected alternative:** Run initial screening once, simulate a fixed top-K, and stop. Rejected because early low-fidelity misranking could hide the true best architecture/mapping.


### Decision 9: Define evidence tiers and claim-to-evidence gating before implementation

The DSE system must define summary, debug, and forensic evidence tiers before implementation work starts. Summary evidence is mandatory for every trusted simulation-backed candidate; debug evidence is mandatory for finalists, failures, or anomalous candidates; forensic evidence is reserved for publication-level or user-selected audit runs. Final report claims must point to evidence ids and concrete artifact files.

**Rationale:** Evidence output is not an afterthought. If evidence is not designed up front, the system can produce rankings that users cannot inspect or replay.

**Rejected alternative:** Emit only `simulation_result.json` and add traces later. Rejected because bottleneck, feasibility, mapping-comparison, and replay claims require different artifact classes.

### Decision 10: Treat the architecture catalog as an extensible product surface

Architecture definitions are split into families, parameter schemas, component registries, instances, constraints, and simulation bindings. A design point can be generated from an architecture family only after validation. A design point can enter the trusted final ranking only when its architecture instance has a valid SystemC or gem5+SystemC binding.

**Rationale:** The local architecture library is known to be incomplete. A family/instance/binding split allows the first implementation to support current Host+FPGA/CIM designs while leaving stable hooks for future architectures.

**Rejected alternative:** Hardcode the current 4-cluster architecture as the design space. Rejected because it prevents serious exploration of memory-rich, diag-heavy, streaming-heavy, debug, and future custom families.

### Decision 11: Make the final report a validated artifact, not a prose summary

The final analysis report must be generated from validated run artifacts. It must separate trusted SystemC/gem5+SystemC-backed conclusions from predicted-only candidates, list limitations, and validate every trusted claim against the evidence index before being accepted.

**Rationale:** The user needs a final analysis result that can be audited, replayed, and discussed. A prose-only report is insufficient for a complex DSE system.

**Rejected alternative:** Let the agent summarize metrics manually at the end of a run. Rejected because manual summaries are easy to overclaim and cannot enforce file/evidence consistency.

## Risks / Trade-offs

- [Risk] The generated spec may be more complete than the current implementation. → Mitigation: label completion evidence explicitly and task implementation work separately.
- [Risk] Multi-fidelity requirements may over-constrain exploratory research code. → Mitigation: require stable external contracts while allowing internal model formulas to evolve behind versioned evidence.
- [Risk] Too many capability files may increase maintenance overhead. → Mitigation: keep five capability boundaries aligned with real subsystem ownership and validation lanes.
- [Risk] Existing tests may not cover every normative scenario. → Mitigation: tasks include a traceability matrix and test-gap closure before any spec is archived as implemented.
- [Risk] gem5/SystemC integration may remain stubbed longer than the spec roadmap implies. → Mitigation: scenarios distinguish L3 standalone completion from L4 full-system completion and require honest status reporting.
- [Risk] The pipeline may produce partial outputs that look like final analysis. → Mitigation: final reports must enforce claim-to-evidence links and label predicted-only candidates as non-final.
- [Risk] DFT workload assumptions could leak into generic layers. → Mitigation: DFT-specific terms are confined to `dft-qe-workload-adapter`; generic specs use opaque operator and metadata fields.
- [Risk] Architecture catalog may grow without simulation binding coverage. → Mitigation: unbound architectures remain candidate-only and cannot enter trusted final ranking.
- [Risk] Mapping search may overfit low-fidelity screening. → Mitigation: finalists require SystemC/gem5+SystemC evidence and feedback-loop convergence reporting.

## Migration Plan

1. Review and refine these OpenSpec artifacts.
2. Define the end-to-end run contract and final analysis report schema before implementing more local evaluator features.
3. Implement documentation restructuring: produce a v2 architecture spec or replace the v1 manual with a capability-indexed version.
4. Add a requirement-to-document traceability matrix linking OpenSpec capabilities/scenarios to the v2 professional architecture document.
5. Align Python/C++ schemas and return types with the IR/backend contracts.
6. Close known Generic SystemC and gem5 blockers before claiming L3/L4 completion.
7. Run targeted validations and update evidence tables.
8. Archive the change only after implementation and verification meet the scenarios.

Rollback strategy: because this change initially adds OpenSpec artifacts only, rollback is deleting `openspec/changes/enhance-generic-dse-framework-spec/`. Once archived, rollback should be handled through a new OpenSpec change that modifies or removes affected requirements.

## Open Questions

- Should the canonical published document be a new `docs/architecture/generic_dse_framework_design_spec_v2.md`, or should v1 be rewritten in place after review?
- What exact evidence threshold will freeze L1/L2/L3 accuracy against QE traces: MAPE, ranking agreement, or per-family tolerance bands?
- Which workloads beyond QE/DFT are required before calling the framework generic in external-facing claims?
- Is L4 gem5 + SystemC required for the first professional spec release, or should it remain explicitly planned until DMA/descriptor/TLM integration lands?
- Should DSE v2 remain Host+FPGA-first per `dse_v2/AGENTS.md`, or should the generic spec support CPU+GPU+FPGA+ASIC/CIM as the long-term architecture target while implementation tasks stage Host+FPGA first?
