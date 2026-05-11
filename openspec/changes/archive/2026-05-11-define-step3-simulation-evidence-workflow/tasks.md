## 1. OpenSpec Step3 Contract

- [x] 1.1 Add `step3-simulation-evidence-workflow` requirements for persisted Step2 input artifacts, pre-simulation validation, replayable request generation, evidence/status artifacts, blocked/untrusted states, and cross-step validation.
- [x] 1.2 Add OpenSpec deltas for end-to-end workflow, generic simulation backend, and multi-fidelity evaluation so Step3 evidence becomes the trusted high-fidelity boundary.

## 2. Step3 Implementation

- [x] 2.1 Implement the Step3 workflow entry point that loads Step2 artifacts from disk, validates handoff trust gates, copies Step2 inputs, and blocks invalid candidates before simulation.
- [x] 2.2 Reconstruct the generic backend request from persisted workload, executable graph, DesignPoint, architecture, mapping, and promotion artifacts without hidden Python state.
- [x] 2.3 Emit `step3_status.json` plus full-flow evidence/report artifacts and downgrade successful-but-incomplete results to untrusted status.
- [x] 2.4 Export the Step3 APIs from the evidence package.

## 3. Cross-Step Tests

- [x] 3.1 Add Step1→Step2→Step3 tests for generic non-QE workloads that verify evidence emission and absence of QE-only required fields.
- [x] 3.2 Add DFT/QE regression tests that preserve adapter-scoped coverage and mapping seeds without making QE metadata global.
- [x] 3.3 Add blocked-handoff tests for unsupported lowering, candidate-only/missing binding, smoke/diagnostic boundaries, illegal mappings, and missing required artifacts.

## 4. Handbook, Traceability, and Validation

- [x] 4.1 Update the architecture handbook with a Step3 audit section, artifact checklist, acceptance gates, and smoke/final-check rule.
- [x] 4.2 Update the OpenSpec traceability matrix with the Step3 change and cross-step validation evidence.
- [x] 4.3 Run Python compile, targeted Step3 tests, full `dse_v2/tests`, and strict OpenSpec validation.
