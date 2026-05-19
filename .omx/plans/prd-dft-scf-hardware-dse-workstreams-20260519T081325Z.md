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
