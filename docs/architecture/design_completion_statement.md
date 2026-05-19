# Design Completion Statement

> Date: 2026-05-18  
> Status: **design-boundary frozen / implementation-evidence gated**  
> Scope: Generic DSE + multi-level simulation + gem5 GenericAccel evidence, with QE full-callgraph offload search as an active proof lane.

## Statement

The repository now has enough architecture material to state that the **system-level design boundaries, claim gates, and implementation acceptance contracts are substantially defined**. It is **not** honest to claim the complete system design is final-delivery complete.

Use this document as the top-level design status statement:

> The Generic DSE system architecture and acceptance boundaries are clear enough for implementation to proceed against a frozen baseline. Several evidence-producing subsystems remain proof-gated or active-change scoped; therefore the project is in **design-boundary frozen, implementation advancing** status, not `deliverable_complete` or final design closure.

## Frozen for implementation

| Area | Frozen baseline | Source of truth |
|---|---|---|
| Stage boundaries | Step1 workload ingestion, Step2 architecture/mapping/co-design, Step3 simulation evidence, Reporting/claim layer | `docs/architecture/system_architecture_overview.md`, `docs/architecture/system_design_frozen_baseline.md` |
| Fidelity trust model | L1/L2 are screening and candidate-generation; L3/L4 are evidence gates; smoke/diagnostic/projection cannot claim final value | `docs/architecture/claim_boundary.md`, `docs/architecture/generic_dse_framework_design_spec_v2.md` |
| Candidate identity | DSE identity must include offload target/bundle identity when offload selection changes candidate semantics | `.omx/plans/prd-complete-dse-qe-callgraph-offload-search.md`, `dse_v2/codesign/qe_callgraph_offload_search.py` |
| QE offload value gate | `valuable_l4` requires non-smoke full QE/gem5 L4, correctness, accelerated replacement consumed by QE, pure QE baseline, GPU context, and positive end-to-end speed | `.omx/plans/prd-complete-dse-qe-callgraph-offload-search.md`, latest `runs/dse/qe_callgraph_offload_value_matrix_*` |
| QE speed judgement | Speed is end-to-end `pure_qe_baseline_elapsed_seconds / patched_qe_elapsed_seconds`; stage/timer/bridge counts are diagnostics only | `docs/architecture/qe_offload_speed_judgement.md`, latest `bundle_speed_diagnostics_report.json` |
| Domain boundary | Core schemas remain domain-neutral; QE/DFT stays in reference workload or plugin boundaries | `docs/architecture/claim_boundary.md`, `openspec/changes/remove-dft-qe-core-adapter/` |

## Still not frozen as final design closure

| Area | Current status | Why not final |
|---|---|---|
| Step2 L1/L2 screening | Active OpenSpec change: `complete-step2-l1-l2-screening` | Still implementation/evidence scoped. |
| QE/DFT core-adapter removal | Active OpenSpec change: `remove-dft-qe-core-adapter` | Boundary is intended, but migration is active. |
| L4 full value closure | Proof-gated | Latest bundle actual-compute is proven but speed is non-positive. |
| Numerical correctness/reference model | Mixed/proof-gated | Generic simulator is timing-only; QE actual-compute rows use explicit correctness gates. |
| Runtime/compiler evidence | Planned/proof-gated | Bundle runtime contract and harness readiness remain blocked until explicit multi-kernel support is implemented. |
| IC/EDA/formal evidence | Optional side evidence | It cannot substitute for full QE/gem5 actual-compute value. |

## Evidence snapshot

Latest folded QE callgraph/offload matrix at the time of this statement:

`runs/dse/qe_callgraph_offload_value_matrix_20260518T124727Z_with_bundle_value_positive_repeat2`

Key status:

- `attempt_count=41`
- `actual_compute_full_qe_evidence_passed_count=32`
- `valuable_l4_count=2`
- `repeatability_stable_valuable_l4_count=1`
- `bundle_single_workflow_l4_evidence_status=bundle_value_proven`
- `bundle_single_workflow_bundle_level_valuable_l4_count=1`
- `deliverable_complete=false`

Latest bundle speed diagnostic:

`runs/dse/qe_bundle_single_workflow_actual_compute_20260518T124150Z_runtime_supported_nscf_stress_fast_driver_repeat3_prelaunch_all_repeat2/bundle_speed_diagnostics_report.json`

- `status=speed_positive`
- `speedup_vs_pure_qe=1.0182902790478408`
- `patched_minus_baseline_seconds=-1.665131803994882`
- `bundle_level_valuable_l4=true`
- stability remains proof-gated; this is not a `deliverable_complete` claim

## Permitted wording

Allowed:

- “System architecture and claim boundaries are frozen enough for implementation.”
- “Core design is converging and has a frozen baseline plus gap matrix.”
- “QE offload DSE has real non-smoke L4 evidence and one positive single-workflow bundle value row, but stable bundle value and deliverable completion remain proof-gated.”
- “Implementation is advancing under evidence gates.”

Not allowed:

- “System design is complete.”
- “Deliverable complete.”
- “Only implementation remains.”
- “Stable bundle-level QE offload value is proven.”
- “Smoke/projection/local tests prove acceleration value.”

## Exit criteria for a future `design_complete` claim

A future design-complete declaration requires all of the following:

1. Active OpenSpec changes that affect architecture boundaries are archived or explicitly marked future/out-of-scope.
2. `system_design_frozen_baseline.md` is the single top-level baseline, and older v0/v1/v2 docs are either referenced as background or superseded.
3. `implementation_gap_matrix.md` has no unknown design-owner rows for in-scope delivery requirements.
4. `claim_boundary.md` has an explicit positive/negative claim table covering DSE, L4, QE, runtime/compiler, numerical correctness, and IC/EDA side evidence.
5. Traceability links PRD/OpenSpec/docs/code/tests/artifacts for every accepted claim.
