## 1. Step2 Low-Fidelity Artifacts

- [x] 1.1 Add Step2 artifact constants and JSON payload helpers for L1 result, L1 promotion decision, L2 result, L2 promotion decision, and low-fidelity summary.
- [x] 1.2 Normalize L1 analytical and L2 TLM evaluator outputs into replayable JSON dictionaries with status, metrics, confidence/uncertainty, provenance, and candidate-generation role.

## 2. Step2 Promotion Integration

- [x] 2.1 Run L1 and required L2 screening for the selected Step2 DesignPoint before final `mapping_promotion_decision.json` is created.
- [x] 2.2 Gate `promoted_for_simulation` on the low-fidelity summary and include low-fidelity reasons, thresholds, scores, and required artifacts in the promotion decision.
- [x] 2.3 Persist low-fidelity artifacts in the Step2 output directory and include them in Step2 artifact validation and DesignPoint replay metadata.

## 3. Step3 Handoff Validation

- [x] 3.1 Extend Step3 input artifact copying/loading to include the low-fidelity Step2 artifacts.
- [x] 3.2 Block before simulation when a promoted Step2 handoff lacks required low-fidelity artifacts or has a failed low-fidelity summary.

## 4. Tests and Validation

- [x] 4.1 Add Step2 tests asserting L1/L2 artifacts exist, are candidate-generation only, and are cited by `mapping_promotion_decision.json`.
- [x] 4.2 Add Step3 tests asserting missing or failed low-fidelity handoff artifacts cause `blocked_before_simulation`.
- [x] 4.3 Run targeted Step2/Step3 pytest tests and `python3 -m compileall dse_v2`.
