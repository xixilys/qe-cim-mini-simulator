## ADDED Requirements

### Requirement: Step2 executes complete L1/L2 screening before Step3 promotion
Step2 SHALL evaluate the selected DesignPoint with a formal L1 analytical evaluator and SHALL evaluate it with L2 TLM when the Step2 low-fidelity policy requires complete screening. Step2 SHALL persist `l1_evaluation_result.json`, `l1_promotion_decision.json`, `l2_evaluation_result.json`, `l2_promotion_decision.json`, and `low_fidelity_screening_summary.json` in the Step2 handoff. Step2 SHALL NOT mark `promoted_for_simulation=true` unless the low-fidelity summary satisfies the configured pre-Step3 gate.

#### Scenario: Complete screening emits required artifacts
- **WHEN** Step2 selects a legal mapping on a bound architecture with default low-fidelity policy
- **THEN** the Step2 handoff contains L1 and L2 result artifacts, both promotion-decision artifacts, and a summary that records `required_for_step3=true` and `passed=true`

#### Scenario: Failed low-fidelity gate blocks Step3 promotion
- **WHEN** L1 or required L2 screening fails, is missing, or is explicitly blocked
- **THEN** `mapping_promotion_decision.json` records the low-fidelity blocker and Step2 SHALL set `promoted_for_simulation=false`

### Requirement: Step2 low-fidelity artifacts remain candidate-generation evidence
Step2 SHALL label L1 and L2 screening artifacts as candidate-generation evidence only. The Step2 status, mapping records, promotion decision, and low-fidelity summary SHALL NOT set `trusted_final_claim=true` or claim a final winner from L1/L2 results.

#### Scenario: L1/L2 success does not create a trusted winner
- **WHEN** both L1 and L2 screening pass for the selected candidate
- **THEN** Step2 may promote the candidate to Step3 simulation but SHALL keep `trusted_final_claim=false` and SHALL require Step3 evidence before trusted ranking
