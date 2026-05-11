## Context

Step1 established `WorkloadPackage`, graph-shape-neutral `ComputeGraph`, adapter registry, and `graph_lowering_report.json`. The remaining risk is that later DSE steps still need a concrete checklist for each workload family: what source is accepted, what the adapter must prove, what mapping seeds are legal, what coverage is required for a full run, and what domain correctness claims remain out of scope unless adapter evidence exists.

The design must keep the core DSE framework domain-neutral while giving implementers enough workflow detail to build and test adapters for ML/tensor, sparse linear algebra, stencil/streaming, graph analytics, database/vector search, DFT/QE, dynamic-control, and custom scientific graphs.

## Goals / Non-Goals

**Goals:**
- Define a normative workload-family workflow that starts at source ingestion and ends at claim-gated final reporting.
- Make adapter-required coverage explicit for every family so non-QE workloads are never checked against QE phase names.
- Define family-specific domain validation boundaries without requiring the generic SystemC backend to prove domain semantics it cannot know.
- Preserve full-flow simulation requirements and smoke/diagnostic disqualification.
- Provide a handbook matrix that Step2+ implementation can use as acceptance criteria.

**Non-Goals:**
- Implement all adapters in this change.
- Define every possible domain metric for every future workload.
- Replace architecture catalog or mapping-search design.
- Claim ML accuracy, sparse residual convergence, graph-query equivalence, or database correctness from generic timing evidence alone.

## Decisions

### Decision 1: Coverage is adapter-declared, with executable-node fallback
Each `WorkloadPackage` adapter declares `required_coverage` as node ids, region ids, or named phases that must appear in full-flow evidence. If not declared, the core workflow uses DFT/QE SCF phases only for `dft_qe`; otherwise it uses the lowered executable graph nodes.

Rationale: this keeps DFT/QE strict while preventing non-QE workloads from being incorrectly blocked by QE-only phase names. Alternative rejected: a single global coverage list, because it cannot represent heterogeneous workload families.

### Decision 2: Workflow families are normative templates, not hardcoded branches
The handbook and OpenSpec define family workflow templates: accepted sources, graph pattern, lowering policy, mapping seeds, simulation evidence, and domain validation. Implementations may add adapters by registering those declarations; the core pipeline consumes the generic declarations.

Rationale: later adapters can be implemented independently without editing the orchestrator for every domain. Alternative rejected: adding direct `if workload == ml` or `if workload == sparse` branches to core DSE.

### Decision 3: Generic timing evidence and domain correctness remain separate
The generic backend can validate graph scheduling, timing metrics, data movement, and artifact completeness. Domain-specific correctness requires adapter-owned validators and evidence, such as ML accuracy tolerance, sparse residual threshold, stencil conservation/error norms, graph-query equivalence, database recall/precision or query-result equivalence, or DFT/QE residual/density/eigen checks.

Rationale: this prevents overclaiming from a timing simulator. Alternative rejected: treating successful SystemC timing execution as universal semantic correctness.

### Decision 4: Reduced, sampled, imported-trace-only, and smoke workloads are visible but non-final
Adapters may emit reduced or diagnostic packages for bring-up, but those packages must declare a non-final claim boundary and cannot satisfy trusted final workflow checks.

Rationale: diagnostic paths remain useful for development without contaminating final DSE conclusions.

## Risks / Trade-offs

- [Risk] Family templates become too rigid for new domains. → Mitigation: require adapters to declare workflow metadata and allow custom adapters to add domain-specific validators while satisfying the common contract.
- [Risk] Dynamic-control workloads are hard to lower. → Mitigation: require bounded, summarized, trace-distributed, or backend-native lowering before final claims; otherwise emit unsupported diagnostics.
- [Risk] Implementers confuse timing evidence with domain correctness. → Mitigation: final report must label generic timing validation separately from adapter-domain validation.
- [Risk] Adapter-declared coverage is incomplete. → Mitigation: validation must report missing coverage declarations and final reports must cite adapter-required coverage explicitly.

## Migration Plan

1. Add OpenSpec requirements for generic workload-family workflows and adapter coverage declarations.
2. Update the architecture handbook with a workload workflow matrix and per-family acceptance checklist.
3. Keep DFT/QE SCF phase coverage as the `dft_qe` adapter workflow, not as a global default.
4. In later implementation goals, add one adapter/test slice at a time using this design: adapter emit → validate package → lower graph → simulate → write evidence → validate report claims.

Rollback is simple for documentation/spec changes: revert the new OpenSpec change and handbook section. Runtime behavior is unaffected until later implementation goals consume the spec.

## Open Questions

- Which non-QE adapter should be promoted first after `generic_json`: ONNX/ML, sparse MatrixMarket/CSR, stencil DSL, graph analytics, or vector-search/database query plan?
- What default domain tolerances should be used for publication-quality ML/sparse/stencil/database validation?
- Should finalist runs require debug evidence by default for all workload families, or only for selected/reported winners?
