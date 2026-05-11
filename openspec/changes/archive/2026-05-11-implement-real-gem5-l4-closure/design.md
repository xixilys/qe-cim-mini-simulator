## Context

The repository already has a trusted L3 standalone SystemC DSE path and a guarded `gem5_systemc` backend mode. The guarded mode currently rejects runs that omit `--gem5-real-l4`, which prevents synthetic gem5 evidence from being mistaken for full-system proof. Existing code also contains the intended L4 surfaces: `Gem5SystemCClosureAdapter.run_verified_l4()`, the gem5 GenericAccel SE harness, the guest L4 driver, `build_gem5_l4_proof()`, and full-flow evidence/report propagation.

The remaining gap is a minimal, auditable closure path that turns a real gem5-driven descriptor/request submission into a bounded trusted L4 transport/timing sample. The design must preserve the current generic heterogeneous SystemC backend, avoid reverting to legacy 4-Cluster assumptions, and avoid overclaiming physics, board, RTL, or comparative winner correctness.

## Goals / Non-Goals

**Goals:**

- Make `gem5_systemc --gem5-real-l4` produce a real `gem5_l4_proof.json` only after descriptor/request ingestion, SystemC backend submission, completion/result writeback, guest-visible success, and passed SystemC result status are observed.
- Propagate passing L4 proof into `verdict.json`, `mapping_simulation_samples.json`, `claim_validation.json`, and final report eligibility for bounded transport/timing replay claims.
- Preserve the explicit failure path for `gem5_systemc` runs without `--gem5-real-l4`.
- Keep existing L3 SystemC behavior and evidence trusted independently of L4 availability.

**Non-Goals:**

- Do not implement a full production gem5 platform, board model, RTL model, or QE numerical correctness validator.
- Do not claim best architecture, best mapping, or Pareto convergence from a single L4 proof.
- Do not redesign architecture catalog generation, Step2 mapping search, workload adapters, or generic SystemC cost models.
- Do not use standalone TLM/MMIO smoke tests or diagnostic replay as trusted L4 evidence.

## Decisions

### Decision: Treat `gem5_l4_proof.json` as the L4 trust boundary

The TrustGate and full-flow evidence writer will treat `gem5_l4_proof.json` as the single machine-checkable proof for gem5+SystemC trust. The proof must contain explicit boolean checks for descriptor/request ingestion, SystemC submission, completion/result writeback, guest-visible success, and SystemC result success, plus source artifact paths.

Alternatives considered:
- Reuse `verdict.json` alone. Rejected because verdicts summarize many evidence classes and do not expose enough L4-specific observability for audit.
- Trust gem5 process exit status alone. Rejected because a successful gem5 process does not prove descriptor ingestion, backend submission, or guest-visible completion.

### Decision: Keep `--gem5-real-l4` as an explicit opt-in

The CLI will continue to reject `backend=gem5_systemc` unless `--gem5-real-l4` is set. This prevents accidental generation of synthetic artifacts and keeps L4 test cost visible to the user.

Alternatives considered:
- Automatically fall back to diagnostic evidence. Rejected because it recreates the synthetic-evidence ambiguity this work is meant to eliminate.
- Always run L4 for all high-fidelity samples. Rejected because L3 standalone SystemC remains a valid high-fidelity path and should not depend on gem5 availability.

### Decision: Bound L4 trust to transport/timing replay

A passing proof enables trusted L4 transport/timing replay claims only. Final reports and claim validation must still state that QE FP64 physics correctness, board correctness, RTL correctness, and comparative winner claims require separate evidence.

Alternatives considered:
- Promote a passing L4 proof to full correctness. Rejected because the proof observes the full-system transport path, not physical board behavior or numerical science correctness.
- Mark all L4 output diagnostic. Rejected because it would ignore the value of real gem5-driven descriptor/completion closure once the proof passes.

### Decision: Implement against existing L4 surfaces

Implementation should use the existing `Gem5SystemCClosureAdapter`, gem5 GenericAccel harness/driver/device logs, `build_gem5_l4_proof()`, and full-flow evidence writer rather than adding a parallel L4 stack.

Alternatives considered:
- Add a new proof generator independent of full-flow evidence. Rejected because it risks divergent trust semantics and duplicate artifact handling.
- Push proof parsing into the gem5 device model. Rejected because DSE evidence assembly belongs in the Python orchestration layer where run artifacts and claim validation are already collected.

## Risks / Trade-offs

- [Risk] The local environment may not have a buildable gem5 binary or SystemC linkage. → Mitigation: retain explicit blockers with `trusted_final_eligible=false` when the real harness cannot run, and verify negative gating separately.
- [Risk] Log-token based proof parsing may be brittle. → Mitigation: require stable tokens from guest-visible status and GenericAccel DPRINTF output, and include raw log paths in the proof for audit.
- [Risk] A single passing L4 sample could be overinterpreted as a complete DSE conclusion. → Mitigation: TrustGate keeps feasibility, transport/timing replay, and comparative ranking as separate claim categories.
- [Risk] L4 work could disturb the healthy L3 path. → Mitigation: run the existing L3 SystemC full-flow and dse_v2 regression suite after implementation.

## Migration Plan

1. Add OpenSpec deltas defining the real L4 closure capability and the bounded updates to existing backend, multi-fidelity, trust-gate, and end-to-end contracts.
2. Update tests so missing `--gem5-real-l4` still fails and a real/passing proof is accepted only when all required proof checks pass.
3. Implement or tighten the minimal L4 proof generation and propagation path using existing adapter/evidence modules.
4. Run OpenSpec validation, generic SystemC backend tests, dse_v2 tests, L3 full-flow replay, negative `gem5_systemc` gating, and real L4 full-flow if the local gem5 harness is available.

Rollback is straightforward: revert this change set and the CLI remains at the current safe state where `gem5_systemc` without `--gem5-real-l4` is blocked and no synthetic L4 evidence is trusted.

## Open Questions

- Whether the local environment has a buildable gem5 GenericAccel binary available for the final real-harness command.
- Whether proof parsing should eventually move from log-token checks to a structured guest/device status file emitted by the gem5 run.
