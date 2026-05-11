## Context

The previous generic DSE OpenSpec baseline established the end-to-end contract and the repository now has trusted vertical-slice evidence for standalone SystemC and a real gem5+SystemC L4 descriptor/request/SystemC/completion path. The remaining design gap is no longer “can one pilot run?” but “can the DSE loop justify feedback-driven architecture or mapping conclusions across candidates without overclaiming?”.

Current anchors:

- `docs/architecture/generic_dse_framework_design_spec_v2.md` §6 defines screening, feedback, and convergence concepts.
- `docs/architecture/generic_dse_framework_design_spec_v2.md` §9 defines the final report and claim evidence table.
- `dse_v2/mapping/search.py` emits legality, seed, candidate, selected, sample, and feedback artifacts for the current seeded search path.
- `dse_v2/evidence/full_flow.py` writes full-flow run evidence, numerical validation, verdicts, mapping artifacts, and L4 proof artifacts.
- `dse_v2/reporting/final_report.py` validates final report claims against run-local evidence.
- `runs/dse/l4_full_flow_real_20260509_162922` is the current trusted real L4 transport proof; its claim boundary is gem5 descriptor/request/SystemC/completion plus generic timing numeric validation, not QE FP64 physics correctness.

The next implementation must convert the single-candidate feedback prototype into auditable multi-candidate feedback and explicit convergence/budget reporting. Reports must keep predicted-only candidates visible but excluded from trusted winners unless each comparative claim has high-fidelity evidence.

## Goals / Non-Goals

**Goals:**

- Add OpenSpec requirements for multi-candidate feedback artifacts, convergence/budget state, trusted comparative ranking, and explicit L4 proof gating.
- Implement a reproducible pilot path that can persist multi-candidate feedback/convergence artifacts for a bounded SystemC/gem5+SystemC DSE run.
- Extend final reports so convergence, budget exhaustion, trusted comparative ranking, predicted-only candidates, and L4 proof boundaries are machine-checkable.
- Preserve the completed L4 evidence boundary: real verified L4 samples may be trusted for transport/timing claims; stub or missing proof remains prototype/blocked.
- Keep numerical validation explicit and scoped to generic SystemC timing outputs unless a future task adds QE FP64 physics references.

**Non-Goals:**

- Do not regenerate QE traces or modify the protected upstream QE tree.
- Do not claim QE FP64 residual, density, eigenvector, or physical SCF correctness from timing-level generic simulator checks.
- Do not require exhaustive simulation of every architecture family in this change.
- Do not replace the current deterministic seeded mapping search with a large Bayesian/NSGA-II optimizer.
- Do not archive the change until OpenSpec validation, tests, and a new feedback/convergence evidence run pass.

## Decisions

### Decision 1: Make feedback state an artifact contract, not an internal optimizer detail

The implementation SHALL persist `mapping_simulation_samples.json`, `mapping_feedback_state.json`, and `convergence_status.json` as run artifacts. These files form the audit surface for promotion, sample trust, ranking correction, and stop/continue decisions.

**Rationale:** The report cannot justify convergence or budget exhaustion from logs or in-memory optimizer state. Persistent JSON artifacts allow tests, reports, and reviewers to verify the loop.

**Rejected alternative:** Keep feedback in `mapping_feedback_state.json` only. Rejected because convergence/budget decisions need a small top-level artifact that final reports and validators can inspect without understanding the whole mapping state schema.

### Decision 2: Treat multi-candidate SystemC evidence as the first comparative path

The first multi-candidate implementation may use standalone SystemC samples for more than one promoted mapping/architecture candidate. Real gem5+SystemC samples are eligible when `gem5_l4_proof.json` passes, but this change does not require running gem5 for every candidate.

**Rationale:** The objective is to unblock feedback/convergence/reporting semantics. Requiring L4 for every promoted candidate would make the first loop too slow and brittle. The report can still include at least one real L4 proof as transport evidence and label other candidates by their actual backend.

**Rejected alternative:** Allow single-sample evidence to claim convergence. Rejected because top-K stability, Pareto stability, or best-architecture claims require comparable candidate evidence or must be labeled non-comparative.

### Decision 3: Use strict trust labels for every sample and claim

Each sample SHALL record backend, fidelity, status, trusted eligibility, evidence ids, metrics, and any missing proof. Final reports SHALL build trusted ranking/Pareto/convergence claims only from samples whose verdict and proof gates pass.

**Rationale:** This prevents blocked/prototype/stub paths from being silently promoted into final conclusions while still preserving useful diagnostics.

**Rejected alternative:** Trust all successful process exits. Rejected because a simulator or gem5 run returning zero is not enough to prove descriptor ingestion, phase coverage, numeric validation, or result writeback.

### Decision 4: Distinguish convergence from budget exhaustion

`convergence_status.json` SHALL record stop reason as one of convergence, budget_exhausted, blocked, user_stopped, or incomplete. Budget exhaustion may produce a final report but SHALL be a limitation, not proof that the global best architecture was found.

**Rationale:** DSE often stops because expensive simulation budget is consumed. Reporting that as convergence would overstate confidence.

**Rejected alternative:** Use a boolean `converged` only. Rejected because it cannot distinguish successful stability from an exhausted budget or a hard backend blocker.

### Decision 5: Keep final recommendation conservative until comparative gates pass

The final report may rank trusted samples and identify a selected candidate only when the comparison set is adequate for the claim type. A single trusted run remains feasibility evidence, not a global best-architecture result.

**Rationale:** The repository already has strong single-run evidence; the next risk is overclaiming it as a comparative design result.

**Rejected alternative:** Select the lowest-latency trusted sample unconditionally. Rejected because family coverage, objective directions, domination, and evidence completeness must be checked first.

## Risks / Trade-offs

- [Risk] Multi-candidate pilots increase runtime. → Mitigation: keep the first budget small and deterministic, and allow SystemC-only comparative samples while preserving optional L4 proof.
- [Risk] Reports could become cluttered with predicted-only and blocked records. → Mitigation: separate trusted ranking, predicted-only appendix, blocked/prototype section, and limitations.
- [Risk] Existing single-run tests may not cover convergence logic. → Mitigation: add focused unit tests for artifact shape, budget exhaustion, convergence status, and report claim gating.
- [Risk] L4 proof could be overgeneralized. → Mitigation: every L4 proof artifact states its transport/timing boundary and does not claim QE FP64 physics correctness.
- [Risk] OpenSpec deltas may duplicate baseline requirements. → Mitigation: use ADDED requirements for concrete artifact and trust-gate refinements rather than rewriting broad baseline requirements.

## Migration Plan

1. Add this change's OpenSpec deltas and validate them strictly.
2. Extend mapping/evidence code to emit multi-candidate sample and convergence-status artifacts.
3. Extend report generation to consume feedback/convergence artifacts and validate comparative/convergence claims.
4. Add or update tests for sample trust labels, budget exhaustion, convergence reporting, final report gating, and L4 proof gating.
5. Run a new reproducible pilot under `runs/dse/` and record numerical validation evidence.
6. Run `python3 -m pytest -q dse_v2/tests`, `openspec validate add-feedback-convergence-reporting --strict --no-color`, and `openspec validate --all --strict --no-color`.
7. Archive only after implementation evidence covers every scenario.

Rollback strategy: revert this change's OpenSpec files and any focused DSE feedback/reporting edits. Existing L3/L4 vertical-slice evidence and previous archived specs remain valid.

## Open Questions

- What default top-K stability threshold should be used once more architecture families are inexpensive enough to simulate repeatedly?
- Should the first publication-quality multi-candidate run require forensic evidence for finalists, or is debug evidence enough until paper figures are generated?
- Which architecture families should be mandatory for the first trusted comparative recommendation beyond the current balanced pilot?
