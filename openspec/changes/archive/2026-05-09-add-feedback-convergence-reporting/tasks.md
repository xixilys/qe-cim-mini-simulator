## 1. OpenSpec Contract

- [x] 1.1 Validate the new OpenSpec design/spec/tasks artifacts for `add-feedback-convergence-reporting`.
- [x] 1.2 Ensure delta specs define multi-candidate feedback samples, convergence/budget artifacts, comparative claim gating, and explicit L4 proof boundaries.

## 2. Feedback and Convergence Artifacts

- [x] 2.1 Extend mapping feedback output so promoted candidates can be represented as multiple high-fidelity samples with per-sample trust labels, evidence ids, and blocker reasons.
- [x] 2.2 Emit `convergence_status.json` with criteria, thresholds, stop reason, convergence boolean, budget status, metric history, and limitations.
- [x] 2.3 Ensure `manifest.json` and `artifact_manifest.json` include the convergence artifact and feedback sample/state artifacts.

## 3. Final Reporting and Claim Validation

- [x] 3.1 Extend `final_report.json` and `final_report.md` to include convergence/budget summary, trusted comparative ranking status, predicted-only candidates, and blocked/prototype limitations.
- [x] 3.2 Extend claim validation so comparative/Pareto/convergence claims require resolved sample, feedback, convergence, verdict, numerical-validation, and L4-proof evidence as appropriate.
- [x] 3.3 Preserve the claim boundary that generic timing numerical validation is not QE FP64 physics correctness.

## 4. Regression and Evidence Runs

- [x] 4.1 Add or update regression tests for multi-candidate sample artifacts, convergence budget exhaustion, report sections, claim gating, and L4 proof sample evidence.
- [x] 4.2 Run a new reproducible feedback/convergence pilot under `runs/dse/` and verify numerical validation evidence is present and passing.
- [x] 4.3 Run `python3 -m pytest -q dse_v2/tests`.
- [x] 4.4 Run `openspec validate add-feedback-convergence-reporting --strict --no-color` and `openspec validate --all --strict --no-color`.
