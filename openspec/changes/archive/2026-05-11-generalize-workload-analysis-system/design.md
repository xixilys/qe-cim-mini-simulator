## Context

DSE v2 already has a domain-neutral `ComputeGraph`, `WorkloadPackage`, adapter registry, workload workflow registry, Step2 mapping workflow, and Step3 evidence workflow. The gap is not a missing IR foundation; it is that project-facing documentation and selected implementation/reporting surfaces still let QE appear as the default workload model rather than as one adapter.

The intended system is a broad workload analysis platform for AI/tensor graphs, scientific computing, sparse linear algebra, stencil/streaming, graph analytics, database/vector search, DFT/QE, and custom workloads. The generic layers must only consume graph structure, tensor/resource metadata, workflow metadata, claim boundaries, and adapter-owned validation artifacts.

## Goals / Non-Goals

**Goals:**
- Make the broad workload analysis system the top-level OpenSpec capability.
- Preserve the existing QE flow as a reference adapter while preventing QE fields from leaking into generic contracts.
- Ensure non-QE workloads have explicit acceptance criteria through Step1 ingestion, Step2 mapping, Step3 evidence, and final reporting.
- Keep implementation scope minimal: strengthen adapter/workflow tests, generic handoff behavior, and user-facing docs.

**Non-Goals:**
- Implement full production importers for external formats such as ONNX, Matrix Market, SQL plans, graph datasets, or CFD DSLs.
- Remove QE adapter compatibility or rewrite existing QE traces.
- Replace backend simulators, architecture catalogs, or optimization algorithms.

## Decisions

### Decision 1: Treat `WorkloadPackage` as the only top-level ingestion contract

Core stages will accept workload input only after it has been normalized into `WorkloadPackage` and `ComputeGraph` artifacts. This keeps domain-specific parsing in adapters and prevents core DSE from growing per-domain branches.

Alternative considered: add first-class core fields for each broad domain. This was rejected because AI, DFT, graph analytics, and database workloads have different correctness semantics and would make the core schema brittle.

### Decision 2: Keep workflow-family semantics data-oriented

Built-in families such as `ml_tensor`, `sparse_la`, `stencil_streaming`, `graph_analytics`, `database_vector_search`, `dft_qe`, and `dynamic_custom` will declare accepted sources, lowering, mapping policies, coverage, unavailable metrics, and domain validation through workflow metadata.

Alternative considered: dispatch on workload family in Step2/Step3/reporting code. This was rejected except for adapter-owned policy hooks because it reintroduces QE-first style domain leakage.

### Decision 3: Scope QE phase coverage to the `dft_qe` adapter

QE node names and SCF phases remain valid coverage for the DFT/QE adapter. They are not allowed as global full-flow requirements for non-QE workloads.

Alternative considered: keep QE SCF coverage as a global default because it is the most mature evidence path. This was rejected because it prevents AI, sparse, graph, database, and custom workloads from becoming first-class analysis targets.

### Decision 4: Implement through minimal generic regression paths

The implementation should add or strengthen tests showing at least two non-QE families can be packaged, mapped, and evidence-checked without QE fields, while keeping a QE regression that proves adapter-scoped coverage remains intact.

Alternative considered: implement many new adapters immediately. This was rejected as unnecessary for proving the architecture; adapter importers can be added later behind the same contract.

## Risks / Trade-offs

- [Risk] Existing documents and scripts may still use QE examples heavily → Mitigation: reframe examples as reference adapter examples and add at least one non-QE example in entry documentation.
- [Risk] Generic tests may pass while report text still implies QE-first authority → Mitigation: include final report and Step3 tests in the implementation tasks.
- [Risk] Domain correctness could be overclaimed from generic timing evidence → Mitigation: require adapter-owned validation artifacts for accuracy, residual, convergence, query equivalence, recall, or physics claims.
- [Risk] External importers remain incomplete → Mitigation: explicitly scope this change to ingestion contracts and representative generated/generic JSON workloads.

## Migration Plan

1. Add OpenSpec deltas for the broad workload analysis capability and affected generic workflow contracts.
2. Update DSE v2 tests and minimal implementation surfaces so non-QE workloads exercise the same Step1→Step2→Step3 pathway.
3. Update DSE v2 user-facing docs to describe QE as a reference adapter.
4. Keep existing QE commands and tests as compatibility regression paths.

Rollback is straightforward: revert this change's OpenSpec artifacts and code/doc edits; no data migration or external dependency is introduced.

## Open Questions

- Which external importer should be implemented first after this change: ONNX-like ML, Matrix Market sparse, graph dataset, database query plan, or CFD/stencil DSL?
- Which non-QE workload family should become the next high-fidelity backend calibration target after QE?
