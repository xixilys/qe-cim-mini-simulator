## Why

The current DSE flow has a trusted standalone SystemC L3 path and correctly blocks `gem5_systemc` from producing synthetic evidence, but it still lacks a minimal real L4 closure path that can produce a passing `gem5_l4_proof.json`. This change is needed now so L4 claims remain honest while enabling gem5+SystemC transport/timing replay to become trusted only when the full descriptor/request, SystemC execution, completion, and guest-visible success path is exercised.

## What Changes

- Define the minimal trusted L4 evidence contract for `gem5_systemc --gem5-real-l4`.
- Require a real L4 proof artifact that records descriptor/request ingestion, SystemC backend submission, result/completion writeback, guest-visible success, and passed SystemC result status.
- Keep the existing no-synthetic-evidence behavior for `gem5_systemc` runs without `--gem5-real-l4`.
- Integrate passing L4 proof into full-flow evidence, mapping samples, verdicts, and claim validation without upgrading the claim scope beyond transport/timing replay.
- Preserve existing trusted L3 standalone SystemC behavior and the generic heterogeneous backend contract.

## Non-goals

- Do not claim QE FP64 physics correctness, board correctness, RTL correctness, or best-architecture selection from the L4 proof alone.
- Do not redesign Step2 architecture mapping, workload adapters, DSE search, or the generic SystemC backend.
- Do not revive synthetic gem5 evidence, smoke-only completion, or legacy 4-Cluster evidence as trusted L4 proof.
- Do not require a full production gem5 platform model beyond the minimal descriptor/request-to-SystemC-to-guest completion closure needed for bounded L4 transport/timing evidence.

## Capabilities

### New Capabilities

- `real-gem5-l4-closure`: Defines the real gem5+SystemC closure proof, accepted claim boundary, and required artifacts for trusted L4 transport/timing replay.

### Modified Capabilities

- `generic-simulation-backend`: Clarify that the trusted L4 path must run through real descriptor/request ingestion, SystemC backend submission, completion writeback, and guest-visible success rather than diagnostic standalone TLM compatibility alone.
- `multi-fidelity-dse-evaluation`: Require `gem5_systemc` samples to remain untrusted unless a passing L4 proof is present, and allow passing L4 proof to create trusted transport/timing samples with bounded claim scope.
- `trust-gate-contract`: Add concrete proof-field and rejection semantics for L4 eligibility.
- `end-to-end-dse-workflow`: Require full-flow L4 evidence export, verdict propagation, claim validation, and replay metadata when `--gem5-real-l4` is used.

## Impact

- Affected OpenSpec contracts: `real-gem5-l4-closure`, `generic-simulation-backend`, `multi-fidelity-dse-evaluation`, `trust-gate-contract`, and `end-to-end-dse-workflow`.
- Affected code paths: `dse_v2/scripts/dse/run_full_flow_pilot.py`, `dse_v2/backends/gem5_systemc_adapter.py`, `dse_v2/evidence/full_flow.py`, and related tests in `dse_v2/tests/`.
- Affected evidence artifacts: `gem5_l4_proof.json`, `verdict.json`, `mapping_simulation_samples.json`, `claim_validation.json`, and run manifests for `gem5_systemc --gem5-real-l4`.
