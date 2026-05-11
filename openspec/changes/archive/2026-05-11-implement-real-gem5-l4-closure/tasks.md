## 1. L4 Proof Contract and Tests

- [x] 1.1 Add or tighten tests proving `gem5_systemc` without `--gem5-real-l4` fails before trusted evidence artifacts are synthesized.
- [x] 1.2 Add or tighten tests proving a passing `gem5_l4_proof.json` requires descriptor/request ingestion, SystemC submission, completion/result writeback, guest-visible success, and passed SystemC result status.
- [x] 1.3 Add or tighten tests proving missing or failed L4 proof fields keep `gem5_systemc` samples untrusted with structured blockers.

## 2. Real L4 Adapter Closure

- [x] 2.1 Ensure `Gem5SystemCClosureAdapter.run_verified_l4()` invokes the real gem5 GenericAccel L4 harness and persists raw gem5 stdout, stderr, log, descriptor/request, completion, and SystemC result artifacts.
- [x] 2.2 Ensure proof extraction reads real harness evidence rather than synthetic placeholders and records stable source artifact paths for audit.
- [x] 2.3 Preserve explicit failure behavior when the gem5 binary, harness config, guest driver, or SystemC backend cannot run.

## 3. Evidence and Trust Propagation

- [x] 3.1 Update `build_gem5_l4_proof()` so all required L4 proof checks are explicit booleans and the overall pass status fails if any required check is missing or false.
- [x] 3.2 Update full-flow evidence export so passing L4 proof propagates into `verdict.json`, `mapping_simulation_samples.json`, and `claim_validation.json` for bounded transport/timing replay claims.
- [x] 3.3 Update blocker propagation so missing, failed, or incomplete L4 proof appears in verdicts, sample records, and final reports without trusted gem5 claims.

## 4. Verification

- [x] 4.1 Run `openspec validate --all` and verify this change remains valid.
- [x] 4.2 Run the generic SystemC backend build/tests and the `dse_v2` pytest suite.
- [x] 4.3 Run a standalone SystemC full-flow pilot to confirm existing L3 evidence remains trusted.
- [x] 4.4 Run the negative `gem5_systemc` command without `--gem5-real-l4` and confirm it exits explicitly before synthetic evidence generation.
- [x] 4.5 Run the real `gem5_systemc --gem5-real-l4` full-flow command when the local gem5 harness is available, or record the explicit missing-harness blocker without claiming L4 completion.
