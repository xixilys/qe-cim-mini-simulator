# Implementation Gap Matrix

> Date: 2026-05-18  
> Status: active tracking matrix. This is an implementation control document, not a completion claim.

## Status legend

| Status | Meaning |
|---|---|
| `implemented` | Code/tests/artifacts exist for the stated baseline. |
| `partial` | Meaningful implementation exists, but evidence or scope is incomplete. |
| `proof_gated` | Design is defined; completion depends on real evidence. |
| `blocked` | A known blocker prevents completion. |
| `planned` | Design exists but implementation has not landed. |
| `out_of_scope_first_pass` | Explicitly excluded from first-pass completion. |

## Gap matrix

| Requirement / design area | Current status | Evidence | Gap / next action |
|---|---|---|---|
| Step1 workload ingestion and graph artifacts | `partial` | `dse_v2/reference_workloads/`, `docs/architecture/system_architecture_overview.md` | Keep generic workload coverage and profile/importer traceability explicit. |
| Step2 architecture/search-space definitions | `partial` | `docs/architecture/architecture_templates/`, `dse_v2/codesign/` | Active change `complete-step2-l1-l2-screening`; keep search-space generation replayable. |
| Step2 offload target identity | `implemented` | `.omx/plans/prd-complete-dse-qe-callgraph-offload-search.md`, tests in `dse_v2/tests/test_complete_dse_offload_target_identity.py` | Continue preventing offload target changes from sharing candidate identity. |
| DSE searches workload/stage/kernel/callsite/bundle offload choices | `implemented/partial` | Latest matrix attempted 8 kernels and emits bundle/search reports | Continue widening useful actual-compute attempts; keep queued/blocked reasons visible. |
| QE full-callgraph inventory | `partial` | `qe_callgraph_inventory.json` in latest matrix | Static full-callgraph parser still explicitly incomplete; dynamic trace anchors mitigate but do not close full static coverage. |
| QE callsite patch manifest | `implemented/partial` | `qe_callsite_patch_manifest.json`, `patches/qe_callsite_offload_hooks/` | Keep bundle patch and runtime capability rows aligned with actual support. |
| Smoke evidence boundary | `implemented` | `classify_l4_offload_value`, anti-downgrade tests | Continue rejecting smoke/dataflow as actual-compute or value. |
| Real non-smoke QE/gem5 actual-compute L4 rows | `partial` | Latest matrix: `actual_compute_full_qe_evidence_passed_count=32` | Not all candidates prove value; blocked rows must remain explicit. |
| Stable row-level QE L4 value | `partial` | Latest matrix: `valuable_l4_count=2`, `repeatability_stable_valuable_l4_count=1` | Stable value is currently narrow and small; do not call deliverable complete. |
| Bundle-level QE L4 value | `partial/proof_gated` | `bundle_single_workflow_l4_evidence_report.json`: `bundle_value_proven`; `bundle_speed_diagnostics_report.json`: latest bundle speedup `1.0182902790478408`, patched is `1.665131803994882 s` faster than pure QE | Do not call stable or deliverable complete yet; repeatability/stability remains proof-gated because nearby stress/fast-driver repeat evidence includes non-positive samples. |
| QE speed-diagnostic reporting | `implemented/partial` | `dse_v2/scripts/dse/build_qe_bundle_speed_diagnostics_report.py`, `docs/architecture/qe_offload_speed_judgement.md`, latest `bundle_speed_diagnostics_report.json` | Extend diagnostics after future runs to include statistical margins and any new workload/bundle campaigns; keep value claims separate. |
| GPU baseline context | `implemented` | Latest matrix: `baseline_gpu_context_observed_count=41`, `baseline_gpu_available_count=41` | Preserve GPU context in every actual-compute baseline comparison. |
| Runtime/compiler multi-kernel bundle harness | `blocked/planned` | `bundle_runtime_contract_report.json`: runtime unimplemented; `bundle_harness_readiness_report.json`: blocked | Implement real multi-kernel selector/output slots/per-callsite provenance before claiming bundle readiness. |
| Generic simulator timing evidence | `implemented with limits` | `model/generic_sim_backend/`, docs note timing-only | Do not use as numeric correctness proof. |
| Numerical correctness reference model | `proof_gated` | QE actual-compute correctness gates; generic sim timing-only statement | Add numeric/reference evidence where claims require computation correctness beyond timing. |
| gem5 GenericAccel descriptor/request/completion evidence | `partial` | `gem5_integration/`, L4 reports | Keep L4 evidence tied to real patched-QE or explicit blocked status. |
| IC/EDA/formal evidence | `out_of_scope_first_pass/proof_gated` | `.omx/context/ic-eda-side-evidence-*` | Use IC VM for side timing/closure evidence when needed; never substitute it for QE/gem5 value. |
| Domain-neutral core boundary | `partial` | `openspec/changes/remove-dft-qe-core-adapter/`, docs claim boundary | Finish active change and keep QE-specific fields outside generic core schemas. |
| Final deliverable completion | `blocked by policy` | PRD requires `deliverable_complete=false` first pass | Do not mark complete until a future PRD explicitly changes the completion contract. |

## Latest evidence pointer

Latest folded evidence matrix used by this gap matrix:

`runs/dse/qe_callgraph_offload_value_matrix_20260518T124727Z_with_bundle_value_positive_repeat2`

Selected counters:

- `attempt_count=41`
- `actual_compute_full_qe_evidence_passed_count=32`
- `actual_compute_not_valuable_l4_count=26`
- `valuable_l4_count=2`
- `repeatability_stable_valuable_l4_count=1`
- `bundle_single_workflow_l4_evidence_status=bundle_value_proven`
- `bundle_single_workflow_bundle_level_valuable_l4_count=1`
- `deliverable_complete=false`
