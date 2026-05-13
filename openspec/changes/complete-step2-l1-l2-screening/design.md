## Context

Step2 currently produces architecture, DesignPoint, mapping, co-design, promotion, and handoff artifacts. Its mapping search records a lightweight `L1_screening` estimate inside each candidate record, but the Step2 handoff does not yet include a formal L1 analytical result, L1→L2 promotion decision, L2 TLM result, or L2→L3 promotion decision for the selected candidate. Existing L1/L2 modules already exist under `dse_v2/dse/` and `dse_v2/models/`, and Step3 is already responsible for L3/L4 evidence.

The change must keep the Step1 → Step2 → Step3 boundary replayable: Step2 writes all low-fidelity artifacts to disk, and Step3 only validates/uses those artifacts before running L3/L4.

## Goals / Non-Goals

**Goals:**

- Run a formal L1 evaluation for the selected Step2 DesignPoint.
- Use an explicit promotion policy to decide whether L2 is required.
- Run L2 TLM when policy requires it, while recording skipped/blocked states when it does not.
- Gate Step3 promotion on the low-fidelity screening summary and persist all relevant artifacts.
- Keep L1/L2 evidence as candidate-generation evidence only.
- Extend Step3 validation so missing or failed required low-fidelity artifacts block simulation before L3/L4.

**Non-Goals:**

- Do not move L1/L2 execution into Step3.
- Do not use L1/L2 outputs as trusted final ranking evidence.
- Do not replace the existing mapping search or SystemC/gem5 backends.
- Do not make the implementation workload-family specific.

## Decisions

### Decision 1: Add Step2-owned low-fidelity handoff artifacts

Step2 will write additive artifacts:

- `l1_evaluation_result.json`
- `l1_promotion_decision.json`
- `l2_evaluation_result.json`
- `l2_promotion_decision.json`
- `low_fidelity_screening_summary.json`

Rationale: Step2 is the owner of pre-simulation candidate screening. Keeping these artifacts in the Step2 handoff preserves replayability and lets Step3 audit the candidate without running low-fidelity models itself.

Alternatives considered:

- Embed all fields into `mapping_promotion_decision.json`: rejected because the promotion decision would become large and harder to diff.
- Store only a summary: rejected because it would hide evaluator details and block later calibration/debugging.

### Decision 2: Make L2 configurable but default-required for complete screening

The Step2 workflow will accept a low-fidelity policy with `require_l2` defaulting to true. L1 always runs for promoted-capable candidates. L2 runs if the L1 policy promotes to L2 or if complete screening requires L2. A skipped L2 is explicit and cannot satisfy a `require_l2=true` gate.

Rationale: the requested behavior is complete L1/L2 functionality. Default-required L2 creates a concrete handoff while preserving future configurability.

Alternatives considered:

- Use `MultiFidelityEvaluator` as-is: rejected because it returns only the final fidelity result and does not persist each layer decision in the Step2 handoff shape.
- Always run L3 from `MultiFidelityEvaluator`: rejected because Step3 owns L3 evidence, replay, and claim validation.

### Decision 3: Normalize evaluator outputs before promotion

L1 and L2 evaluator outputs will be normalized into JSON dictionaries with `fidelity_level_achieved`, `status`, metrics, uncertainty/confidence, provenance, and candidate-generation role. L1 dataclass outputs will be converted via `to_dict()` and augmented with status/confidence fields needed by the promotion engine.

Rationale: current evaluator return shapes differ. A normalized Step2 artifact avoids leaking evaluator-specific Python objects into handoff JSON.

Alternatives considered:

- Change all evaluators to a single dataclass now: rejected as broader than this change.
- Let Step3 normalize: rejected because Step3 should not interpret low-fidelity model internals.

### Decision 4: Gate Step3 promotion on low-fidelity summary, not low-fidelity trust

`mapping_promotion_decision.json` will include a `low_fidelity_screening` section and `promoted_for_simulation` will require the summary to pass. The summary does not create `trusted_final_claim`; it only says the selected candidate completed the required L1/L2 screening needed to enter Step3.

Rationale: this preserves the architecture rule that L1/L2 are candidate generators while making the pre-Step3 gate complete and auditable.

Alternatives considered:

- Treat a failed L2 as diagnostic but still run L3: rejected for the default path because it would not satisfy the new complete screening contract.
- Let Step3 ignore low-fidelity artifacts: rejected because the handoff would be incomplete and not self-auditing.

## Risks / Trade-offs

- [Risk] L2 TLM may be coarse and not graph-faithful enough for all workload families → Mitigation: record the result as candidate-generation evidence with explicit provenance and never trusted final evidence.
- [Risk] Default L2 execution may make Step2 slower → Mitigation: L2 is Python-only and inexpensive relative to L3/L4; policy can later relax `require_l2` if needed.
- [Risk] Existing tests may assume exact artifact lists → Mitigation: add artifacts additively and preserve existing filenames.
- [Risk] PromotionEngine expects fields not present in L1 dataclass output → Mitigation: normalize L1/L2 results before evaluating promotion decisions.

## Migration Plan

1. Add OpenSpec deltas for Step2 and multi-fidelity evaluation requirements.
2. Add Step2 low-fidelity artifact constants and helper functions.
3. Run L1/L2 screening in `run_step2_architecture_mapping_workflow()` after the selected DesignPoint is built and before Step2 promotion is finalized.
4. Persist low-fidelity artifacts and add Step3 validation.
5. Update tests for Step2 handoff artifacts and Step3 missing/failed artifact blocking.
6. Validate with targeted Step2/Step3 tests and compile checks.

Rollback is safe because the artifacts are additive; disabling the low-fidelity gate can be done by reverting the Step2 helper integration and Step3 validation checks.

## Open Questions

- The exact long-term calibration loop between L2 and L3 remains future work.
- Whether `require_l2` should remain default true for all workload families can be revisited after runtime evidence is collected.
