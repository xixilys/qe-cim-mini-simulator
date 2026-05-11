## Context

Step1 now emits domain-neutral `WorkloadPackage`, source `ComputeGraph`, graph-lowering report, executable graph, workflow metadata, and required coverage. Step2 now consumes that handoff and persists architecture, DesignPoint, legality, mapping, promotion, feedback, and convergence artifacts. Step3 is the first stage allowed to turn a promoted candidate into trusted high-fidelity evidence, so it must be replayable from disk and must reject incomplete or diagnostic paths before they can be confused with final DSE conclusions.

The design is constrained by the generic-DSE requirement: non-QE workloads must pass through the same workflow without QE-only fields, while DFT/QE remains an adapter-owned workflow example. The design also preserves the hard evidence gate: smoke, diagnostic, fixed-timing, prototype, predicted-only, and candidate-only artifacts are never sufficient for trusted final ranking.

## Goals / Non-Goals

**Goals:**

- Define a Step3 workflow that consumes persisted Step2 artifacts rather than hidden Python objects.
- Validate Step2 promotion, artifact completeness, lowering eligibility, mapping legality, and claim boundary before simulation.
- Build a replayable generic SystemC/gem5+SystemC simulation request from disk artifacts.
- Emit a complete Step3 evidence bundle, final report, claim validation, and structured `step3_status.json`.
- Test Step1→Step2→Step3 flows for non-QE workloads, DFT/QE adapter regression, and blocked/untrusted handoffs.

**Non-Goals:**

- Do not make Step3 a QE-specialized path or require QE-only phase names for generic workloads.
- Do not use smoke, driver hello, fixed-timing, or diagnostic replay as completion evidence.
- Do not declare a global best architecture from a single trusted pilot sample; comparative/convergence claims still require comparable trusted samples and convergence evidence.
- Do not introduce new simulator dependencies or rewrite the Step1/Step2 contracts.

## Decisions

1. **Step3 consumes copied Step2 artifacts as its input contract.**
   - Rationale: reviewers need to reproduce the simulation request from run-local files; hidden in-memory objects are not auditable.
   - Alternative rejected: pass Step2 Python return objects directly into simulation. That is faster locally but cannot be replayed or independently audited.

2. **Pre-simulation validation is a hard gate.**
   - Step3 checks required Step2 artifacts, promotion decision, dynamic artifact validation, graph-lowering status, full-workload eligibility, selected-mapping violations, and diagnostic claim boundaries before launching the backend.
   - Alternative rejected: run the simulator first and downgrade later. That wastes simulation budget and risks diagnostic paths being reported as successful samples.

3. **Use the existing generic SystemC bridge and full-flow evidence writer.**
   - Rationale: the Step3 boundary should orchestrate handoff/replay/evidence, not fork a second simulator or report schema.
   - Alternative rejected: add a Step3-only backend schema. That would duplicate request/result logic and increase the risk of QE-only drift.

4. **Trusted status derives from final evidence gates, not simulator exit code alone.**
   - Step3 writes `trusted_full_flow_evidence_emitted` only when `verdict.json`, `claim_validation.json`, and the full-flow evidence contract pass. Successful but incomplete evidence remains `simulation_completed_untrusted`.
   - Alternative rejected: treat any `simulation_result.status == passed` as trusted. That ignores missing artifacts, smoke boundaries, and domain validation limits.

5. **Cross-step tests are mandatory.**
   - Step3 is validated by running real Step1 package creation, Step2 artifact emission, and Step3 evidence generation for representative workloads. Unit tests that fabricate only Step3-local structures are insufficient.

## Risks / Trade-offs

- **Risk: Step2 artifact schema changes break Step3 replay.** → Mitigation: Step3 validates the artifact set dynamically and tests assert copied Step2 inputs and request reconstruction.
- **Risk: generic workloads accidentally inherit QE coverage requirements.** → Mitigation: non-QE cross-step tests assert absence of QE-only tokens and verify workflow-required coverage is adapter/family derived.
- **Risk: a single trusted sample is overreported as a winner.** → Mitigation: final reports may mark feasibility trusted while keeping `trusted_winner` false until comparative/convergence evidence exists.
- **Risk: simulator executable missing in a clean environment.** → Mitigation: Step3 writes `blocked_simulator_unavailable` with structured reasons rather than synthesizing success.
- **Risk: blocked candidates disappear from audit history.** → Mitigation: Step3 always writes `step3_status.json` and copies available Step2 inputs into `step2_input/`.

## Migration Plan

1. Add the Step3 workflow entry point and export it from `dse_v2.evidence`.
2. Add cross-step tests for generic sparse, database/vector-search, DFT/QE, unsupported lowering, missing binding, smoke boundary, illegal mapping, and missing artifact cases.
3. Update the generic DSE handbook and traceability matrix with the Step3 artifact checklist and final-gate rules.
4. Run Python compile, targeted Step3 tests, full `dse_v2/tests`, and strict OpenSpec validation.
5. Archive the change only after the implementation and documentation evidence match every scenario.

## Open Questions

- The first Step3 implementation targets the existing standalone generic SystemC backend. Future work should add the same persisted-handoff gate for real gem5+SystemC L4 proof when that harness is enabled.
- Comparative/convergence ranking across multiple trusted Step3 samples remains a later optimization-loop expansion, not part of this single-candidate Step3 boundary.
