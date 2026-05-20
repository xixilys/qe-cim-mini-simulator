# PRD — DFT/QE Full-SCF Hardware DSE Workstreams

**Status:** approved planning source / not execution-complete
**Parent plan:** `ralplan-dft-scf-hardware-dse-workstreams`
**Source requirements:** `.omx/specs/deep-interview-dft-scf-hardware-dse-codesign.md`

## Objective

Implement the next-stage workstreams for a DFT/QE full-SCF evaluated hybrid hardware DSE and co-design system, preserving a domain-neutral control plane while adding DFT-specific strict workload bundles, realistic candidate templates, hierarchical search, claim-specific tool evidence gates, and anti-downgrade reporting.

## Scope

### In scope

- Lane J integration spine and contract governance.
- Step1–Step5 artifact ownership and ID propagation.
- Strict six-class DFT/QE workload bundles.
- Two-tier release/exploratory hardware candidates with seed-source provenance.
- Hierarchical funnel search contracts.
- Claimed-kernel promotion gates for FPGA/ASIC claims.
- Wave 1.5 thin end-to-end trace.
- Full-SCF evaluated hybrid reporting with host/transfer/sync costs included.
- Docs/manual/runbook synchronization.

### Out of scope for first execution waves

- Calling Wave 1.5 final completion.
- Full-SCF device-resident accelerator claims.
- Board-level measurement unless later required.
- Replacing generic control-plane contracts with DFT-only contracts.

## Users / consumers

- Manual parallel lane owners.
- `$team` execution lanes.
- `$ralph` verifier/fix loop.
- Future report readers evaluating claim validity.

## Requirements

### R1 — Lane J Integration Spine

Lane J must define and govern:

- canonical schema registry/versioning;
- strict bundle contract;
- candidate/tier contract;
- evidence/adjudication/report handoff contract;
- `campaign_id`, `workload_run_id`, `trial_id` propagation;
- DFT-profile candidate binding map connecting Step2 hierarchical search IDs
  to frozen seven-axis release candidate IDs without claim upgrade;
- DFT-profile hardware completion workplan enumerating release-candidate ×
  major-kernel × hard-gate work items for manual/parallel closure without
  treating shared smoke evidence as candidate-specific PPA;
- DFT-profile hardware closure shard queue for assigning candidate × kernel
  units across parallel lanes without fabricating candidate-specific RTL/HLS or
  tool evidence;
- DFT-profile hardware closure unit-provenance staging that writes
  candidate/kernel-scoped source/tool/command/transcript metadata needed by
  later parsers while keeping raw evidence, hard-gate passes, PPA, Pareto,
  hardware completion, and deliverable completion fail-closed;
- DFT-profile trial state ledger binding Step2 search candidates, evidence
  rows, Step5 report refs, and goal-audit refs to the generic
  Campaign/WorkloadRun/Trial lifecycle without adding DFT fields to generic
  schemas;
- DFT-profile hardware closure parser-run artifacts that read evidence-intake
  rows, write parsed stage-result files only from existing candidate-specific
  raw evidence, and keep all hard-gate adjudication/completion claims
  fail-closed;
- DFT-profile hardware closure gate-adjudication artifacts that consume parsed
  evidence, record per-stage hard-gate verdicts, and keep release completion,
  PPA, and trusted Pareto claims fail-closed until later all-unit closure;
- DFT-profile hardware closure release-gate artifacts that roll all
  candidate/kernel hard-gate verdicts up to hardware-completion eligibility
  while keeping final deliverable completion separate;
- IC/EDA availability bridge artifacts that record real local/SSH tool
  reachability and raw attempts while explicitly labeling the artifact as
  availability-only (`not_kernel_ppa`) and preventing any hardware-completion,
  PPA, trusted-Pareto, or deliverable-completion upgrade from tool reachability
  alone;
- release vs exploratory isolation;
- migration/deprecation policy;
- cross-lane compatibility tests.

### R2 — Step ownership

Implement enforceable Step1–Step5 ownership:

- Step1: workload facts/bundles/profiles.
- Step2: candidate generation/search provenance/promotion blockers.
- Step3: raw execution requests/results/tool transcripts.
- Step4: adjudication/calibration/claim validation/evidence verdicts.
- Step5: reports/rankings/Pareto/frontier/claim boundaries.

### R3 — Wave 1.5 thin trace

Before broad Wave 2, prove:

```text
strict workload bundle
→ release-tier DMA/HBM or transpose candidate
→ tool transcript or blocker
→ Step4 adjudication
→ Step5 report
```

Wave 1.5 is progress-only and cannot be described as MVP, vertical-slice completion, or final closure.

### R4 — Claim-specific gates

For any candidate-accelerated kernel:

```text
golden correctness
→ HLS C-sim or RTL sim
→ HLS C-synth or RTL synth
→ Vivado synth/implementation for FPGA claim
→ DC synth/timing/area for ASIC claim
```

DC-only evidence must fail FPGA claims. Vivado-only evidence must fail ASIC claims.

### R5 — Full-SCF evaluated hybrid reporting

Reports must separate:

- kernel speedup;
- end-to-end SCF evaluated speedup;
- host-bound compute cost;
- transfer cost;
- synchronization/queueing/layout cost;
- evidence level per kernel;
- candidate-level claim eligibility.

CPU-bound I/O, SCF control, convergence, diagonalization, and mixing stay costed.

## Workstreams

Use lanes A–J from the consensus plan:

- A Workload/profile.
- B SCF cost model.
- C Hardware search space.
- D Search/co-design policy.
- E Kernel RTL/HLS.
- F IC/EDA/Vivado automation.
- G Full-SCF hybrid prototype.
- H Evidence adjudication.
- I Docs/manual sync.
- J Integration spine and contract governance.

## Acceptance Criteria

- `strict_bundle_rejects_missing_assets` exists and passes for touched bundle validators.
- `exploratory_candidate_excluded_from_formal_pareto` exists and passes for touched search/reporting paths.
- `unavailable_tool_log_is_blocker_not_pass` exists and passes for touched evidence gates.
- `dc_only_rejected_for_fpga_claim` exists and passes.
- `vivado_only_rejected_for_asic_claim` exists and passes.
- `step5_reports_host_transfer_sync_costs` exists and passes for touched Step5/reporting paths.
- `artifact_ids_propagate_campaign_workload_trial_scope` exists and passes where artifact refs are produced.
- `dft_trial_state_ledger_ties_search_evidence_step5_audit` exists and passes for the DFT trial-ledger artifact path.
- `dft_trial_state_machine_rejects_invalid_or_claim_upgrading_transitions` exists and passes for the DFT trial-ledger validator.
- `dft_candidate_binding_map_is_step5_visible_and_fail_closed` exists and
  passes for binding-map generation, Step5 reporting, and goal-audit checks.
- `dft_hardware_completion_workplan_is_step5_visible_and_fail_closed` exists
  and passes for candidate/kernel/stage work-item expansion and audit checks.
- `dft_hardware_closure_shards_are_step5_visible_and_fail_closed` exists and
  passes for parallel closure queue generation and audit checks.
- `dft_hardware_closure_packets_are_step5_visible_and_fail_closed` exists and
  passes for per-shard closure packet/runbook generation, expected evidence
  filename enumeration, command-template surfacing, Step5 reporting, and audit
  checks.
- `dft_hardware_closure_candidate_bundles_are_step5_visible_and_fail_closed`
  exists and passes for packet-referenced candidate bundle templates, actual
  bundle-payload/hash validation, evidence-root path containment, Step5
  reporting, and audit checks while keeping raw evidence, PPA, Pareto, and
  deliverable completion fail-closed.
- `dft_hardware_closure_unit_provenance_is_step5_visible_and_fail_closed`
  exists and passes for candidate/kernel-scoped provenance staging while
  keeping raw stage evidence count zero and preventing hard-gate, PPA, Pareto,
  hardware-completion, or deliverable-completion upgrades.
- `dft_hardware_closure_raw_stage_materialization_is_step5_visible_and_fail_closed`
  exists and passes for copying/wrapping existing candidate/kernel source-flow
  outputs into packet-expected raw filenames while keeping registration,
  parser output, hard-gate adjudication, PPA/Pareto, hardware-completion, and
  deliverable completion separate.
- `dft_hardware_closure_raw_transcript_registration_is_step5_visible_and_fail_closed`
  exists and passes for SHA-256 registration of already-present
  candidate-specific raw transcript files while keeping parser output,
  hard-gate adjudication, PPA/Pareto, hardware-completion, and deliverable
  completion separate.
- `dft_hardware_closure_evidence_intake_is_step5_visible_and_fail_closed`
  exists and passes for candidate-specific bundle/evidence file-presence
  intake while keeping hard-gate adjudication, PPA, Pareto, and deliverable
  completion fail-closed.
- `dft_hardware_closure_adjudication_is_step5_visible_and_fail_closed` exists
  and passes for unit × hard-gate stage accounting while keeping all stages
  `not_adjudicated` and no PPA/Pareto/deliverable claim upgraded without parsed
  candidate-specific evidence.
- `dft_hardware_closure_parsed_evidence_is_step5_visible_and_fail_closed`
  exists and passes for expected parser-output manifests across the five
  hard-gate stages while keeping parser output separate from final adjudication.
- `dft_hardware_closure_parser_run_is_step5_visible_and_fail_closed` exists
  and passes for parser-run artifacts that produce parsed outputs only from
  existing candidate-specific raw evidence and unit-level source/tool/command
  provenance, reject shared microkernel smoke as candidate-specific closure,
  expose missing raw-stage and real DC target-library discovery blockers
  explicitly (`missing_dc_synth_ddc_design_database`,
  target-library/gtech/unmapped/zero-area DC blockers), require `dc_synth.ddc`
  for ASIC raw evidence with no substitute from mapped Verilog/logs/reports, and
  keep hard-gate passes, PPA/Pareto, and deliverable completion separate.
- `dft_hardware_closure_gate_adjudication_is_step5_visible_and_fail_closed`
  exists and passes for parsed-evidence-driven per-stage hard-gate verdicts
  while keeping release completion, FPGA/ASIC PPA, trusted Pareto, and
  deliverable completion fail-closed.
- `dft_hardware_closure_release_gate_is_step5_visible_and_fail_closed` exists
  and passes for candidate/release hard-gate rollup, allowing hardware
  completion eligibility only after all unit gates pass while keeping
  deliverable completion separate; any missing, blocked, failed, or
  not-adjudicated unit keeps the release blocked.
- `ic_eda_availability_bridge_is_step5_visible_and_not_ppa` exists and passes
  for real tool-reachability probe intake, raw-attempt visibility, and
  fail-closed reporting that keeps availability separate from kernel PPA,
  Vivado/DC closure, trusted Pareto, and deliverable completion.
- `step_artifact_ownership_rejects_cross_writes` exists and passes for canonical ownership validation.
- `wave15_trace_reaches_step5_without_completion_claim` exists and passes once Wave 1.5 is implemented.
- Docs/manual/runbook changes accompany code/schema/evidence changes.

## Milestones

1. Wave 0: PRD/test-spec and lane ownership complete.
2. Wave 1: Lane J contracts and minimal canonical schemas pass compatibility tests.
3. Wave 1.5: progress-only thin trace reaches Step5.
4. Wave 2: first real transcript/blocker enters Step4/Step5.
5. Wave 3: major claimed kernels have evidence rows.
6. Wave 4: full-SCF evaluated hybrid integration reports host and transfer costs.
7. Wave 5: evidence-complete trusted Pareto and final anti-downgrade audit.

## Risks

- Candidate explosion: mitigate with budgets, funnel cutoffs, replayable `SearchState`.
- Wrong abstraction freeze: mitigate with binary freeze/thaw gates after Wave 1.5 and first real evidence.
- Fake PPA: fail closed and require raw transcripts/tool versions.
- Host-bound cost hiding: Step5 cost fields required.
- Docs drift: docs sync is an acceptance gate.


## Code Quality Review Addendum — 2026-05-19

This PRD remains **planning and review documentation only**. The current repository already has partial guardrails for the DFT/QE workstreams, but the acceptance criteria above are not execution-complete until the named invariants exist as runnable tests and the Wave 1.5 trace emits Step5 artifacts.

### Current repo evidence anchors

- Domain-neutral core protection is already tested by `dse_v2/tests/test_contracts_canonical.py` and `dse_v2/tests/test_dft_claim_contract.py`: generic schema/IR/mapping layers must not absorb DFT/QE-specific semantics except through the explicit DFT profile/reference-workload boundary.
- Lane J contract primitives are present in `dse_v2/contracts/schema_registry.py`, `dse_v2/contracts/artifact_catalog.py`, and `dse_v2/contracts/entities.py`; these are the correct place to extend campaign/workload/trial IDs, ownership metadata, artifact refs, and schema/version governance.
- Step3/Step4/Step5 separation is already enforced by `dse_v2/evidence/step3_workflow.py`, `dse_v2/evidence/step4_adjudication.py`, `dse_v2/reporting/final_report.py`, and `dse_v2/tests/test_step3_step4_step5_ownership.py`. New Wave 1.5 work must reuse that split instead of adding another report shortcut.
- DFT-specific parsers, modes, candidate policy, and evidence ledgers currently live under `dse_v2/reference_workloads/` with regression coverage in `dse_v2/tests/test_dft_step1_frontdoor.py`, `dse_v2/tests/test_dft_mode_coverage.py`, `dse_v2/tests/test_dft_step2_policy.py`, and `dse_v2/tests/test_dft_candidate_evidence_ledger.py`.
- Existing docs already encode the main anti-overclaiming rules in `docs/architecture/dft_scf_hardware_dse_design_manual.md`, `docs/benchmarks/generic_dse_simulation_system_handbook_v1.md`, and `dse_v2/docs/GENERIC_DSE_FULL_FLOW_REPORTING.md`; future code/schema changes must keep those manuals synchronized.

### Review findings and documentation requirements

| Finding | Risk | Required documentation / implementation guard |
|---|---|---|
| CQ-1: The PRD mixes DFT/QE proof requirements with a domain-neutral DSE control plane. | Contract drift could push DFT-only fields into generic `core/`, `mapping/`, or common schema paths. | Keep DFT-specific bundle facts, parser metadata, and workload-class semantics behind `dse_v2/reference_workloads/`; update `docs/architecture/dft_scf_hardware_dse_design_manual.md` when a DFT-specific field is introduced. |
| CQ-2: The named acceptance criteria are stronger than the currently visible test names. | A worker could claim PRD completion because related tests pass while missing the exact invariant/fixture required by this plan. | Each implementation slice must either add the exact named invariant test or map it in the task result with the file/function that proves equivalent behavior. |
| CQ-3: Step5 reporting exists, but full-SCF evaluated hybrid reporting needs explicit host/transfer/sync/queue/layout cost fields. | Kernel-only speedups could be presented as end-to-end SCF acceleration. | Update Step5 report schemas/docs whenever cost fields change; reports must separate kernel speedup from evaluated full-SCF speedup and include host-bound, transfer, sync/queue, and layout terms. |
| CQ-4: EDA evidence gates depend on external tool availability. | Missing `dc_shell`, VCS, or Vivado could be silently downgraded to synthetic pass evidence. | Record real IC/EDA probes and tool versions before fallback; unavailable/failing tools are Step3 blockers and must fail Step4 FPGA/ASIC claim promotion. |
| CQ-5: Release/exploratory isolation is central to trusted Pareto quality. | Exploratory or model-only candidates could leak into trusted ranking/frontier artifacts. | Step5 docs and report schemas must identify candidate tier, evidence tier, and claim eligibility; trusted Pareto/frontier excludes exploratory, blocked, fake-PPA, and wrong-claim-type rows. |
| CQ-10: Search candidates, per-candidate evidence rows, Step5 report refs, and goal-audit refs can drift without a trial state ledger. | A run may look report-complete while candidate IDs, trial IDs, or blocker reasons are not resumable/auditable. | DFT-specific `dft_trial_state_ledger.json` must record Campaign/WorkloadRun/Trial IDs, legal transitions, artifact refs, blockers, and next actions; it remains orchestration evidence only and cannot self-promote claims. |
| CQ-6: `.omx/plans/` is ignored by the repo and may be absent from worker worktrees. | PRD review updates can disappear from normal worker commits, and worker-local review/edit flows can fail if the leader `.omx/plans` artifact is not materialized. | Worker commits that modify this PRD must materialize the plan path, use `git add -f .omx/plans/prd-dft-scf-hardware-dse-workstreams-20260519T081325Z.md`, and mention that the file is an OMX plan artifact. |
| CQ-7: Repo front-door docs still present a generic-only cleanup boundary. | Readers can interpret `README.md` / `CLAUDE.md` as forbidding the active DFT/QE profile objective, while this PRD requires DFT/QE work behind adapter/profile boundaries. | Follow-on docs work should align front-door wording to "generic core with active DFT/QE profile/adapter workstreams" without making the core DFT-only. |
| CQ-8: Current grep evidence found exact invariant names only in planning artifacts. | Acceptance may be over-claimed before executable tests exist for each named invariant. | Implementation tasks must add the exact invariant tests or record an explicit equivalent-test mapping in their completion evidence. |
| CQ-9: The design manual encodes the right anti-overclaiming rules but does not point at this PRD/test-spec pair. | Future implementers may update the manual without seeing current Wave 1 / Wave 1.5 gates. | Follow-on docs work should link `docs/architecture/dft_scf_hardware_dse_design_manual.md` to this PRD and `test-spec-dft-scf-hardware-dse-workstreams-20260519T081325Z.md`. |

### Review-gated implementation checklist

Before any lane claims a PRD acceptance item as complete, the task result must include:

1. the changed code/schema/doc files and owning Step/lane;
2. the exact invariant test name or explicitly mapped equivalent test path;
3. evidence that DFT/QE-specific logic did not enter generic core/mapping contracts;
4. Step3 raw evidence, Step4 adjudication, and Step5 reporting boundaries for any claim-affecting artifact;
5. real IC/EDA probe evidence or an explicit blocker label for FPGA/ASIC evidence gates;
6. docs/manual/runbook sync references for every changed public contract, schema, or report field;
7. front-door documentation wording remains consistent with the approved generic-core plus DFT/QE-adapter direction.

## Execution Handoff

Recommended first execution mode: `$team` for Wave 1 + Wave 1.5, then `$ralph`/`verifier` for sequential closure of failing invariants. Use `$ultragoal` when durable multi-wave goal tracking is needed.
