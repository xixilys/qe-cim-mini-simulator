## Why

Step2 now persists generic workload, architecture, mapping, and promotion artifacts, but the next boundary must prove that Step3 can replay those artifacts from disk and produce trusted full-flow evidence without hidden Python state. This change defines the Step3 simulation/evidence contract so later DSE conclusions cannot be confused with smoke, diagnostic, prototype, predicted-only, or candidate-only results.

## What Changes

- Define Step3 as the persisted Step2 handoff consumer and SystemC/gem5+SystemC evidence producer.
- Require Step3 to validate Step2 promotion, artifact completeness, lowering eligibility, mapping legality, and claim boundaries before simulation.
- Require Step3 to copy Step2 input artifacts into its run directory and emit replayable simulation/evidence/report artifacts.
- Add cross-step Step1→Step2→Step3 validation coverage for generic non-QE workloads and the DFT/QE adapter boundary.
- Preserve strict final gates: smoke, diagnostic, prototype, fixed-timing, predicted-only, and candidate-only paths cannot satisfy trusted final checks.

## Capabilities

### New Capabilities
- `step3-simulation-evidence-workflow`: Step3 handoff validation, simulation request replay, full-flow evidence emission, and blocked/untrusted status handling.

### Modified Capabilities
- `end-to-end-dse-workflow`: Clarify the Step3 boundary, required Step2-to-Step3 artifacts, cross-step replay, and final workflow statuses.
- `generic-simulation-backend`: Require backend requests to be rebuildable from persisted Step2 artifacts and to carry Step2 handoff provenance.
- `multi-fidelity-dse-evaluation`: Clarify that Step3 high-fidelity samples are the first eligible trusted evidence source and that lower-fidelity/smoke/prototype samples remain non-final.

## Impact

- Affected code: `dse_v2/evidence/step3_workflow.py`, `dse_v2/evidence/__init__.py`, Step3 tests under `dse_v2/tests/`, and existing evidence/reporting/backend handoff paths.
- Affected docs: generic DSE architecture handbook and OpenSpec traceability matrix.
- No new external dependencies. The workflow reuses the existing generic SystemC backend and full-flow evidence writer.
