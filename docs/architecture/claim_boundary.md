# Claim Boundary

> Date: 2026-05-18  
> Status: normative claim-boundary guide for current architecture and evidence reports.

## 1. Rule

A claim is allowed only when the required evidence exists and the claim text stays within that evidence boundary. Missing evidence must be reported as `partial`, `proof_gated`, `blocked`, or `planned`.

## 2. Allowed and forbidden claims

| Topic | Allowed now | Forbidden now | Required evidence to upgrade |
|---|---|---|---|
| Overall architecture | Architecture boundaries and acceptance gates are frozen enough for implementation. | System design is fully complete; only implementation remains. | Archived/closed active design changes and a fully green gap matrix. |
| Complete DSE | Generic DSE control model is defined and partially implemented. | Full DSE deliverable is complete. | End-to-end replayable search with full evidence and final claim validation. |
| L1/L2 screening | Screening/pruning/ranking hints. | Trusted final value or final winner. | L3/L4 evidence plus claim validation. |
| SystemC/generic simulator | Timing/resource evidence within declared model limits. | Numerical correctness or QE physical correctness by itself. | Numeric/reference validation artifacts. |
| gem5 GenericAccel | Software-visible L4 proof when descriptor/request/execute/completion pass. | Value without correctness/replacement/speed gates. | Full value gate row. |
| QE offload row value | `valuable_l4` only for non-smoke full QE/gem5 L4 rows with correctness, replacement consumption, baseline, and positive speed. | `valuable_l4` from smoke, projection, sidecar, descriptor-only, or local unit tests. | Same gate, plus repeatability if making stable value claims. |
| QE bundle value | Bundle actual-compute can be proven separately from bundle value. | Bundle-level `valuable_l4` while end-to-end bundle speed is non-positive. | Single-QE-workflow full-bundle actual-compute, correctness, replacement, and positive end-to-end speed. |
| GPU baseline | GPU availability is baseline context and must be recorded when present. | GPU availability proves offload value. | Offload value still needs full QE/gem5 value gate. |
| IC/EDA | Optional side evidence for timing/closure/RTL feasibility. | IC/EDA evidence replaces QE/gem5 value. | QE/gem5 actual-compute value remains mandatory for QE offload claims. |
| First-pass report | First-pass value discovery with blockers and `deliverable_complete=false`. | Deliverable complete. | Future PRD that changes first-pass completion contract and all gates green. |

## 3. Speed claim boundary

QE offload speed is measured as end-to-end wall-clock ratio:

```text
speedup_vs_pure_qe = pure_qe_baseline_elapsed_seconds / patched_qe_elapsed_seconds
```

A speed signal is positive only when the ratio is strictly greater than `1.0`. Positive speed alone is not value; it must be combined with L4 provenance, correctness, replacement, and baseline gates.

For multi-stage QE workflows, the comparison includes the same frozen workflow steps on both sides. Stage deltas, QE timers, bridge invocation counts, and bridge launch counts are diagnostic evidence only. They explain the speed result, but they cannot replace the end-to-end ratio or upgrade a non-positive bundle into `valuable_l4`.

Normative speed guide: `docs/architecture/qe_offload_speed_judgement.md`.

## 4. Current QE evidence boundary

Latest folded matrix:

`runs/dse/qe_callgraph_offload_value_matrix_20260518T124727Z_with_bundle_value_positive_repeat2`

Current claim:

- Row-level stable value exists for one `subspace_rotation` stress-bandgrid configuration.
- Bundle actual-compute evidence now includes one single-QE-workflow full-bundle positive-speed value row.
- Latest bundle speed diagnostic: `speedup_vs_pure_qe=1.0182902790478408`, `patched_minus_baseline_seconds=-1.665131803994882`, so the latest bundle run is `speed_positive` and the folded bundle gate is `bundle_value_proven`.
- Bundle stability is still proof-gated: nearby same-family stress/fast-driver repeat evidence includes a non-positive sample, so this is not a stable or deliverable-complete claim.
- First-pass report remains `deliverable_complete=false`.

## 5. Review checklist before any stronger claim

Before upgrading any wording, verify:

1. The claim maps to a named artifact and exact counter/status.
2. The artifact is from a non-smoke path when claiming actual computation or value.
3. The report itself has not been contradicted by blockers or `deliverable_complete=false` policy.
4. Active OpenSpec changes do not leave the claimed design area open.
5. Tests cover the specific anti-downgrade risk, not only dataflow mechanics.
