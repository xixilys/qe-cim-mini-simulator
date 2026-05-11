## Context

Step1 now provides a stable generic workload handoff: `WorkloadPackage`, source `ComputeGraph`, `graph_lowering_report.json`, optional `executable_graph.json`, workflow metadata, required coverage, and source-to-executable mapping. Step2 is the next review boundary: it must turn that lowered workload into auditable architecture candidates and mapping candidates that Step3+ simulation/evidence can consume mechanically.

The current repository already contains an initial architecture catalog and mapping implementation, but the design manual and OpenSpec requirements need a Step2-specific review contract. Without that contract, later implementation goals can accidentally treat one balanced pilot architecture or a QE-oriented mapping seed as the whole DSE design space, or can pass hidden in-memory mapping decisions to simulation without persisted audit artifacts.

## Goals / Non-Goals

**Goals:**
- Define Step2 inputs from Step1 and Step2 outputs for Step3+ as stable artifact contracts.
- Specify architecture catalog completeness, validation, binding status, and trusted-final eligibility rules.
- Specify DesignPoint assembly requirements, including mapping, data placement, scheduling, precision/fallback policy, and replay metadata.
- Specify mapping-search requirements: legality matrix, workload-family seed policies, candidate lifecycle, screening/promote handoff, feedback state, and selected mapping record.
- Define review gates that prevent candidate-only, prototype, unbound, predicted-only, smoke, or QE-hardcoded paths from being treated as final Step2 outputs.
- Update the architecture handbook and traceability matrix so a reviewer can audit Step2 independently from Step1 workload ingestion.

**Non-Goals:**
- Implement a full Bayesian/NSGA-II optimizer in this change.
- Require every architecture family to have a completed SystemC/gem5+SystemC binding immediately.
- Require domain-specific parser or correctness-validator work; those remain adapter responsibilities from Step1 and later workload goals.
- Declare a final best architecture from documentation alone.
- Modify protected QE source trees.

## Decisions

### Decision 1: Step2 consumes artifacts, not adapter internals
Step2 SHALL consume only `WorkloadPackage`, `ComputeGraph`/`executable_graph`, `graph_lowering_report`, workflow metadata, required coverage, and generic node/tensor/cost fields. It SHALL NOT call back into adapter-specific internals to discover hidden mapping assumptions.

Rationale: this keeps Step2 generic and replayable for ML, sparse, stencil, graph analytics, database/vector-search, DFT/QE, and custom workflows. Alternative rejected: letting each adapter directly construct backend-specific mappings, because that would bypass legality artifacts and make final reports unauditable.

### Decision 2: Architecture catalog status gates trusted claims
Architecture families and instances may be present as exploration candidates even when binding is incomplete, but their status labels must be explicit. Only instances with valid constraints and executable SystemC/gem5+SystemC binding coverage may become trusted-final candidates.

Rationale: the catalog must be extensible while preserving claim discipline. Alternative rejected: excluding all unbound future families, because that would prevent design-space planning and later family expansion.

### Decision 2a: Step2 has a multi-architecture screening wrapper over the single-architecture handoff primitive
The single-architecture workflow remains the compatibility primitive for Step3: it writes `design_point.json`, `mapping.json`, `mapping_promotion_decision.json`, legality, seed, candidate, feedback, convergence, and validation artifacts in the same run directory shape. The multi-architecture Step2 wrapper runs that primitive for each selected catalog instance and writes `architecture_screening_records.json` as an aggregate index over per-architecture run directories.

Rationale: Step1 is allowed to evolve internally as long as its serialized workload handoff remains valid, and Step3 must not be forced to understand a new aggregate-only artifact. Alternative rejected: replacing the existing Step2 run directory with a single cross-architecture artifact, because that would break Step3 replay and hide per-candidate audit details.

### Decision 3: Mapping search is workflow-aware but not domain-hardcoded
Mapping seeds may use workload-family workflow metadata and adapter-declared policy ids, but the generic mapping core consumes node ids, op types, tensor sizes, architecture capabilities, and legality reasons. DFT/QE policies are adapter-scoped examples, not global defaults.

Rationale: Step1 made workload-family metadata explicit, so Step2 can use it without reintroducing QE-specific branches. Alternative rejected: generic global seed lists containing hardcoded QE node names, because that would fail non-QE workloads.

### Decision 4: Step2 output is a candidate queue plus evidence-ready artifacts
Step2 does not prove final performance by itself. Its completion means the system can produce replayable DesignPoints, mapping candidates, screening results, promotion decisions, and selected records that are ready for SystemC/gem5+SystemC sampling in Step3+.

Rationale: final ranking requires high-fidelity evidence. Alternative rejected: treating L1/L2 screening scores as Step2 completion evidence for best architecture selection.

## Risks / Trade-offs

- [Risk] The Step2 contract becomes too heavyweight for small bring-up runs. → Mitigation: allow summary/debug/forensic evidence modes, but require explicit diagnostic-only labels for bring-up paths.
- [Risk] Architecture families without bindings clutter reports. → Mitigation: preserve candidate-only records but block trusted-final eligibility until binding validation passes.
- [Risk] Workload-family seeds bias search too strongly. → Mitigation: require generic baseline seeds, candidate lifecycle artifacts, and promotion/budget records so seed effects are reviewable.
- [Risk] Data placement and schedule details are under-modeled in first implementation. → Mitigation: require explicit unavailable/placeholder labels and prevent hidden defaults from entering trusted claims.
- [Risk] Step2 repeats Step1 workload validation. → Mitigation: Step2 only checks that Step1 artifacts are present, valid, and resolvable; domain correctness remains adapter-owned.
- [Risk] Multi-architecture screening is mistaken for a final architecture decision. → Mitigation: aggregate records use `candidate_generator_only` semantics and keep final winner claims blocked until Step3 evidence and final claim validation.

## Migration Plan

1. Add OpenSpec requirements for Step2 architecture/mapping workflow and deltas for architecture, multi-fidelity, end-to-end, and generic IR contracts.
2. Update the architecture handbook with a Step2 review section covering input contract, output artifacts, gates, and audit checklist.
3. Update the OpenSpec traceability matrix with the new Step2 change and its coverage.
4. Validate all OpenSpec specs strictly.
5. Later implementation goals may then extend catalog validation, DesignPoint generation, mapping search, and screening/promotion code against this contract.

Rollback is documentation-only: revert the new OpenSpec change and handbook/traceability edits. Runtime behavior is unaffected by the proposal itself.

## Open Questions

- Which architecture families should be mandatory in the first Step2 implementation run: host baseline, balanced, memory-rich, streaming-heavy, low-power, debug, or custom?
- Should Step2 require data-placement and schedule-placement artifacts immediately, or allow an explicit minimal mapping-only mode for the first implementation slice?
- What promotion budget and top-K stability thresholds should be used for the first non-QE workload families?
- Which architecture families require L4 gem5+SystemC proof versus L3 standalone SystemC for finalist evidence?
