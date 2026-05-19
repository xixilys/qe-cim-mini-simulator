# Current Architecture Traceability Matrix

> Date: 2026-05-18  
> Status: current cross-reference for design-boundary freeze and implementation tracking.

## 1. Source documents

| Source | Role | Status |
|---|---|---|
| `docs/architecture/design_completion_statement.md` | Top-level design status wording | Current |
| `docs/architecture/system_design_frozen_baseline.md` | Consolidated implementation baseline | Current |
| `docs/architecture/implementation_gap_matrix.md` | Requirement-to-status gap tracker | Current |
| `docs/architecture/claim_boundary.md` | Allowed/forbidden claim guide | Current |
| `docs/architecture/qe_offload_speed_judgement.md` | QE offload speed formula and speed-claim boundary | Current |
| `docs/architecture/system_architecture_overview.md` | Broad architecture overview | Background/current, still v0 |
| `docs/architecture/generic_dse_framework_design_spec_v2.md` | Subsystem design specification | Current detailed reference |
| `.omx/plans/prd-dse-codesign-system.md` | Final system contract intent | Planning/contract, not completion proof |
| `.omx/plans/prd-complete-dse-qe-callgraph-offload-search.md` | QE full-callgraph offload DSE PRD | Active Ralph scope |
| `.omx/plans/test-spec-complete-dse-qe-callgraph-offload-search.md` | QE offload anti-downgrade test spec | Active Ralph verification |
| `openspec/changes/complete-step2-l1-l2-screening/` | Active Step2 screening change | Active |
| `openspec/changes/remove-dft-qe-core-adapter/` | Active generic-core boundary change | Active |

## 2. Requirement traceability

| Requirement | Design doc | Code / tests | Latest evidence |
|---|---|---|---|
| Domain-neutral Generic DSE core | `system_design_frozen_baseline.md`, `claim_boundary.md` | `dse_v2/codesign/`, `dse_v2/evidence/` | Active OpenSpec boundary remains open. |
| Step1/Step2/Step3/Reporting stage split | `system_architecture_overview.md`, `system_design_frozen_baseline.md` | `dse_v2/scripts/dse/run_full_flow_pilot.py`, `dse_v2/evidence/full_flow.py` | Partial implementation; not final completion. |
| Offload-target identity layer | `.omx/plans/prd-complete-dse-qe-callgraph-offload-search.md` | `dse_v2/codesign/qe_callgraph_offload_search.py`, `dse_v2/tests/test_complete_dse_offload_target_identity.py` | Implemented with tests. |
| Search workload/stage/kernel/callsite/bundle to offload | QE PRD + frozen baseline | `build_qe_callgraph_l4_multi_probe_report.py`, `run_qe_callgraph_offload_l4_campaign.py` | Latest matrix attempts 8 kernels and emits bundle/search reports. |
| Reject h_psi-only completion | QE PRD + claim boundary | `test_qe_offload_search_anti_downgrade.py` | Guarded; first-pass completion remains false. |
| Reject smoke-as-compute/value | QE PRD + claim boundary | `classify_l4_offload_value`, anti-downgrade tests | Guarded. |
| Record GPU baseline context | QE PRD + claim boundary | L4 runners and speed report | Latest matrix: 41 observed / 41 available. |
| Real QE/gem5 L4 value gate | QE PRD + claim boundary | L4 runners, value gate tests | Latest matrix: 2 raw valuable rows; 1 stable repeatable row. |
| Judge QE offload speed without smoke/projection shortcut | `qe_offload_speed_judgement.md`, `claim_boundary.md` | `build_qe_bundle_speed_diagnostics_report.py`, `test_bundle_speed_diagnostics_are_value_neutral_and_end_to_end` | Latest bundle speed report: `speedup_vs_pure_qe=1.0182902790478408`, `status=speed_positive`; stability remains proof-gated. |
| Bundle single-workflow gate | `claim_boundary.md`, gap matrix | `build_bundle_single_workflow_l4_evidence_report`, multi-probe builder | Latest matrix: bundle status folded as `bundle_value_proven`; stable/deliverable completion not claimed. |
| Runtime/compiler bundle support | frozen baseline + gap matrix | Bundle runtime contract/readiness reports | Blocked/runtime unimplemented. |
| IC/EDA boundary | claim boundary + PRD | `.omx/context/ic-eda-side-evidence-*` | Optional side evidence only. |
| Final design completion wording | design completion statement | docs + checklist | Not claimed. |

## 3. Latest evidence bundle

`runs/dse/qe_callgraph_offload_value_matrix_20260518T124727Z_with_bundle_value_positive_repeat2`

This bundle is evidence for current QE offload DSE progress, not system-wide deliverable completion.
