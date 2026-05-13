## Why

Step2 currently performs architecture/mapping selection plus lightweight `L1_screening`, but it does not run the full L1 analytical → L2 TLM promotion chain before handing a candidate to Step3. This leaves the Step2 promotion artifact weaker than the architecture contract: candidates can enter L3 without auditable L1/L2 results, promotion decisions, budgets, and uncertainty records.

## What Changes

- Add a complete Step2 low-fidelity screening stage that evaluates the selected DesignPoint at L1 and, when policy requires, L2 before Step3 promotion.
- Persist machine-readable L1/L2 artifacts in the Step2 handoff directory, including evaluator results, promotion decisions, and a summary suitable for Step3 replay/audit.
- Extend Step2 promotion decisions so `promoted_for_simulation` cites L1/L2 screening status, confidence, uncertainty, budget, and blockers.
- Preserve the existing rule that L1/L2 outputs are candidate-generation evidence only and never final trusted ranking evidence.
- Keep Step3 as the L3/L4 evidence layer; Step3 consumes and validates the new Step2 low-fidelity artifacts but does not run L1/L2 itself.
- No **BREAKING** changes to existing Step2 artifact names; new artifacts are additive.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `step2-architecture-mapping-workflow`: Step2 promotion must include full L1/L2 screening artifacts and gate Step3 promotion through explicit L1/L2 policy.
- `multi-fidelity-dse-evaluation`: L1/L2 low-fidelity evaluation results and promotion decisions must be persisted in the Step2 handoff and remain candidate-generation evidence only.

## Non-goals

- Do not move L1/L2 execution into Step3.
- Do not claim final winners, Pareto membership, or domain correctness from L1/L2 results.
- Do not require real gem5 L4 execution for the Step2 L1/L2 screening path.
- Do not redesign the generic simulator or SystemC JSON IPC.

## Impact

- `dse_v2/mapping/step2_workflow.py`: Step2 orchestration and handoff artifacts.
- `dse_v2/mapping/search.py`: candidate records may reference richer low-fidelity evidence.
- `dse_v2/dse/analytical_evaluator.py`, `dse_v2/dse/tlm_evaluator.py`, `dse_v2/dse/multi_fidelity.py`, `dse_v2/promotion/promotion_engine.py`: evaluator and promotion integration surfaces.
- `dse_v2/evidence/step3_workflow.py`: handoff validation for additive L1/L2 artifacts.
- `dse_v2/tests/`: Step2 and Step3 cross-step regression coverage.
- `openspec/specs/step2-architecture-mapping-workflow/spec.md` and `openspec/specs/multi-fidelity-dse-evaluation/spec.md`: requirement updates.
