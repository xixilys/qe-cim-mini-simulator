## Why

P0/P1 L4 evidence is now available, so the next design step is to move beyond a single trusted pilot into auditable feedback-driven DSE: multiple candidates must be promoted, sampled, compared, and stopped by explicit convergence or budget criteria. Without this change, reports can show a trusted single run but still cannot justify multi-candidate architecture/mapping recommendations.

## What Changes

- Add concrete feedback-loop artifacts for promoted candidates, high-fidelity samples, ranking corrections, and next-candidate decisions.
- Add convergence and budget reporting so DSE termination is explained as converged, budget-exhausted, blocked, or user-stopped rather than implied by available samples.
- Extend final reporting to separate trusted feasibility, comparative ranking, Pareto/frontier claims, predicted-only candidates, and remaining limitations.
- Make L4 gem5+SystemC proof artifacts explicit now that the GenericAccel descriptor/request/SystemC/completion path can produce verified evidence.
- No breaking API changes are intended; existing single-pilot SystemC evidence remains valid but is not enough for global best-architecture claims.

## Capabilities

### New Capabilities

- None. This change refines the existing DSE, fidelity, backend, and report capabilities rather than introducing a separate top-level capability.

### Modified Capabilities

- `multi-fidelity-dse-evaluation`: Add concrete feedback, convergence, promotion-budget, and multi-candidate sample requirements.
- `end-to-end-dse-workflow`: Add final report and workflow requirements for convergence status, trusted comparative ranking, and replayable feedback-loop artifacts.
- `generic-simulation-backend`: Add explicit L4 `gem5_l4_proof` evidence expectations for trusted gem5+SystemC samples.

## Impact

- Affected code: `dse_v2/mapping/`, `dse_v2/evidence/`, `dse_v2/reporting/`, `dse_v2/scripts/dse/`, and tests under `dse_v2/tests/`.
- Affected evidence artifacts: `mapping_feedback_state.json`, `mapping_simulation_samples.json`, new or extended convergence/budget artifacts, `final_report.json`, `final_report.md`, `claim_validation.json`, and `gem5_l4_proof.json`.
- Affected documentation/specs: OpenSpec deltas for multi-fidelity evaluation, end-to-end workflow, and generic simulation backend.
- Dependencies: no new external dependencies.
