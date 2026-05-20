# DFT/QE Full-SCF Hardware DSE Parallel Workstreams

**Status:** planning/manual supplement; not a completion claim.
**Scope:** Step5 evidence-closure coordination for the DFT/QE full-SCF hardware DSE proof path.
**Boundary:** the generic DSE core owns domain-neutral campaign, trial, search, promotion, evidence-reference, and report contracts. The DFT plugin/profile owns QE workload descriptors, SCF kernel taxonomy, DFT-specific candidate templates, raw evidence adapters, and DFT claim-gate policy.
**Active HIGH-fix plans:** `.omx/plans/prd-dft-workload-profile-high-fixes-20260520T102113Z.md`;
`.omx/plans/prd-dft-audit-high-fix-ralplan-20260520T165732Z.md`

## Current strict state (2026-05-20)

- Workload admission is the six representative SCF descriptor-plus-runnable
  bundle contract.  Generated fixture/pseudo bundles remain scaffolding until
  real QE reference outputs are attached and hashed.
- The prototype boundary is full-SCF evaluated hybrid: host-bound I/O, SCF
  orchestration, convergence, diagonalization, mixing, transfer,
  synchronization, queueing, and layout costs stay in end-to-end timing/energy
  and never count as acceleration benefit.
- Candidate/kernel claims are strict per-kernel claims.  FPGA rows need
  golden + sim + synth + Vivado implementation evidence; ASIC rows need golden
  + sim + synth + DC target-library timing/area evidence plus `dc_synth.ddc`.
- The current all-288 run
  `runs/dse/wave36_step5_real_source_flow_all288_20260520T061902Z` makes the
  36 × 8 matrix hardware-release-gate eligible, not deliverable-complete:
  `stage_gate_passed_count=1440`, `unit_gate_passed_count=288`,
  `candidate_gate_passed_count=36`, `hardware_completion_eligible=true`, and
  `deliverable_complete=false`.
- Current-goal L4 transport proof is present for the 36 × 6 target.
  `current_goal_l4_bridge/` is the exact structured crosswalk/provenance handoff;
  `runs/dse/current_goal_l4_regenerated_36x6_20260520T091000Z` contains 216/216
  row-level gem5 L4 proofs with `passed=true`; and the Step5 L4 binding has
  `status=passed`, `current_goal_l4_bound=true`, and
  `l4_software_visible_proof_present=true`.  This is not deliverable completion:
  QE baseline/correctness/reference gates still block trusted speedup and final
  release claims.  The old 9 × 4 crosswalk is explicitly insufficient.
- The six-SCF QE reference lane is split: QE 6.7 `/usr/bin/pw.x` found local
  pseudos but failed fail-closed (mostly SIGABRT/returncode `-6`, with OpenMPI-aborted returncode `1` rows for slow slab/projector cases), while the tuned QE 7.5
  bundle at `runs/dse/dft_scf_six_class_qe75_reference_tuned_20260520T085312Z`
  records hashes only for rows that have both `JOB DONE` and verified SCF
  convergence.  The QE 7.5 tuned bundle now has `status=passed`, `admitted=true`,
  all six convergence-gated reference hashes, and layered `workload_profiles/`
  artifacts.  It is Step1 reference characterization, not final hardware/PPA or
  deliverable-complete evidence.
- The workload/profile/audit HIGH-fix lane has a tested canonical split between
  applicability, design identity, evaluation policy, release policy,
  feature-derived coverage, and fail-closed QE reference admission.  Its current
  proof path is regression tests, stale-term scanner
  `authoritative_stale_count=0`, and the source-hash-backed
  `dft_audit_semantic_closure.json` artifact.  That artifact closes semantic
  audit findings only; it still must not be reported as full PPA closure or
  final system completion.

## 1. Parallel workstream map

| Lane | Owns | Output | Cannot claim |
|---|---|---|---|
| Step5 evidence closure | Candidate/kernel evidence packets, raw transcript registration, parser readiness, gate adjudication, release rollup | Per-unit evidence rows, blockers, gate verdicts, release-gate status | Full deliverable completion while any required unit is missing, blocked, failed, or not adjudicated |
| Candidate expansion | Release/exploratory architecture candidates, parameter provenance, workload-aware screening inputs | Candidate records, search-space deltas, queue-policy metadata, promotion blockers | Trusted Pareto winners without Step5 evidence gates |
| Search scaling | Scheduling and prioritization for expanded candidate/kernel matrices | Work queues, shard plans, calibrated refinement batches | Hardware value from analytic or model-only screening |
| Docs/manual sync | Manual updates for changed artifacts, gates, stale terms, and claim boundaries | Current runbook text and traceability notes | New implementation behavior without matching tested artifacts |
| Verification | Targeted tests, schema checks, audit scans, and evidence-root safety checks | Command output and audit status | Success from partial or shared-smoke evidence |
| Workload/profile HIGH fixes | Canonical split, coverage derivation, reference-admission policy, and docs status | Updated DFT profile/search/reference semantics plus tests and manual text | Full HLS/RTL/FPGA/ASIC PPA closure or deliverable-complete status |

### 1.1 HIGH-fix execution tranche status

The HIGH tranche from
`.omx/plans/prd-dft-workload-profile-high-fixes-20260520T102113Z.md` and
`.omx/plans/prd-dft-audit-high-fix-ralplan-20260520T165732Z.md` closes the
profile/search/reference-admission audit issues only.  It does not close the
full DFT/QE hardware DSE deliverable.

Workstream owners should keep these policy boundaries explicit:

1. **Applicability/offload scope** — `dft_phase_hotspot_selection` belongs to
   applicability metadata such as `applicability_assignments`.  Changing it may
   affect compatibility or queue routing, but must not change
   `design_candidate_id`, design legality, or design score.
2. **Design identity** — `design_candidate_id` is stable over design semantics
   only: algorithm, schedule/runtime, mapping/data layout, microarchitecture,
   and interface/descriptor protocol.  It excludes workload labels,
   phase/hotspot applicability, evidence policy, release policy, tool status,
   and claim labels.
3. **Evaluation policy** — evidence-fidelity/promotion policy schedules or
   gates evidence through evaluation metadata.  It must not participate in
   design legality or design score.
4. **Release/exploratory policy** — release eligibility and exploratory queue
   isolation are DFT policy metadata.  Legacy candidate-tier aliases must not be
   emitted as Step2 search parameters, and exploratory rows must not enter
   formal Pareto by parameter manipulation.  Trial-ledger audit rows may report
   the derived lane, but registry trial params must not persist legacy
   release-lane aliases.
5. **Feature-derived coverage** — `required_kernel_gates` are derived from
   raw input facts, QE-resolved facts, and derived scale features.  Manual
   `stress_tags` are display/suite-intent annotations only.  Coverage artifacts
   should expose `gate_derivation_reasons` for auditability.
6. **Fail-closed QE reference admission** — final real-QE evidence requires a
   local/reused converged QE output file, final SHA-256, raw-output hash match,
   normalized summary hash, and verified convergence.  Hash-only caller
   material remains provenance and must not pass final admission.

Current HIGH-fix evidence is regression-test output plus updated generated
artifacts showing the split.  Report this lane as audit HIGH fixed only; do not
upgrade it into hardware/PPA or deliverable-complete status.

## 2. Step5 evidence-closure lanes

Step5 should run as candidate/kernel-scoped lanes, not as a single monolithic closure pass. Each lane handles one release candidate plus one major kernel and follows the same fail-closed ladder:

1. closure packet exists for the exact candidate/kernel unit;
2. unit provenance exists and does not upgrade claims;
3. source-flow planning validates the exact candidate/kernel source-flow directory, manifest, and hash;
4. candidate-specific raw files are materialized only from rows that passed source-flow planning;
5. raw transcript registration records hashes for files already under the evidence root;
6. parsers produce stage-specific evidence records;
7. gate adjudication proves the required golden, simulation, synthesis, FPGA, and/or ASIC stages;
8. release rollup succeeds only after every required unit passes.

The accelerated-kernel set remains the eight major DFT/QE SCF kernels: FFT/iFFT/fFFT, 3D transpose/layout conversion, Hψ local potential path, kinetic add, nonlocal projector, complex GEMM/GEMV tile, reduction/dot-product tree, and DMA/HBM movement engine. Host-bound SCF stages must keep explicit cost accounting and must not be counted as acceleration benefit.

## 3. Scaling target: 36 candidates × 8 kernels

The immediate coordination shape is a 36-candidate by 8-kernel matrix, or 288 candidate/kernel evidence units before FPGA/ASIC branch expansion. Treat each unit as independently blockable and independently auditable.

Wave34 inserts a required source-flow planning layer before broad Wave33-style
lane execution.  The plan must enumerate all 288 units, bind each unit to at
most one source-flow directory, validate candidate/kernel manifest identity,
record source manifest hashes, and report planned, valid, blocked,
missing-source-flow, wrong-candidate, wrong-kernel, reused-source, and
provenance-mismatch counts.  This layer exists to prevent one candidate's eight
smoke/microkernel flows from being copied into other candidates as fake
closure.

After the source-flow plan is valid, Wave33-style lanes can execute the 36×8
closure matrix.  Each lane owns one exact release-candidate/kernel unit and
advances only that unit through raw materialization, transcript registration,
parser output, hard-gate adjudication, and release-gate rollup input.  Lane
outputs may be aggregated, but they must not be merged into a pass claim unless
their candidate ID, kernel ID, stage ID, evidence-root path, hashes, source
manifest, and claim type all match.

Use this matrix to plan parallelism:

- shard by candidate family when tool setup or template code is shared;
- shard by kernel when golden traces, HLS/RTL harnesses, or parser logic is shared;
- keep release-tier and exploratory-tier queues separate;
- never let an exploratory unit satisfy a release gate unless it is explicitly promoted and rebound through the release candidate contract;
- report aggregate progress as counts of passed, blocked, failed, missing, and not-adjudicated units, not as a percentage-only success claim.

A release candidate is hardware-completion eligible only when all eight required kernel rows are either proven accelerated under the applicable claim type or explicitly host-bound with host cost accounted. Partial closure is useful scheduling evidence, but it is not a release success.

## 4. Search and candidate expansion

Candidate expansion should widen the DFT plugin search surface without changing generic core contracts:

- add or adjust DFT candidate templates through DFT profile/plugin artifacts, not through core IR assumptions;
- preserve release/exploratory queue-policy metadata, parameter provenance, and promotion blockers on every generated candidate;
- use analytic and model-level screening only to prioritize Step5 work, not to bypass evidence gates;
- record why a candidate is selected for closure, deferred, demoted, or promoted;
- keep fixed hand-picked candidates labeled as seeds or vertical-slice probes unless a replayable search generated and screened them;
- keep `design_candidate_id` separate from evaluation-row `candidate_id`: evidence
  fidelity / promotion policy can schedule or gate an evaluation row, but it must
  not create a new stable design identity.

For 36 candidates, the useful expansion artifact is not just the candidate list.
It must also show parameter ranges, family coverage, feature-derived workload
coverage, screening/pruning reasons, and the Step5 work items generated from the
search output.

## 5. Wave32 status and lesson

Wave32 advanced one release candidate across all eight major kernels through the candidate/kernel hard-gate path.  That is one-candidate closure progress only.  It does not close the 36×8 release matrix, does not make the DFT/QE full-SCF hardware DSE deliverable complete, and must not be extrapolated to candidates or kernels that did not pass the same candidate-specific gates.

Wave32 also established a specific anti-downgrade rule: raw-stage materialization may index or stage all eight candidate/kernel units, but that is only progress. Success requires later lanes to prove all eight units through registration and gate adjudication.

Therefore:

- materialization can show that eight expected units were discovered, copied, or wrapped into packet paths;
- materialization must still keep claim-upgrading fields false and `deliverable_complete=false`;
- registration must hash and bind the actual candidate-specific raw transcripts for all eight units;
- parser and gate lanes must prove the required stage evidence for all eight units;
- one missing, blocked, failed, shared-smoke, or not-adjudicated unit blocks candidate-level success.

Do not summarize a materialized-only Wave32 packet as “8/8 complete” unless the registration and gate reports also prove 8/8 for the same candidate.  The safe wording for materialization-only evidence is “8 units materialized pending registration/gate proof” until those later artifacts pass.  For the current Wave32 result, the safe stronger wording is “one candidate × all 8 kernels passed; full 36×8 release remains blocked.”

## 6. Aggregate Step5 runner intent

The aggregate Step5 runner is intended to assemble parallel lane outputs into one Step5-visible rollup.  It should report candidate/kernel counts and blocker IDs across the 36×8 matrix, preserve links to the per-lane artifacts, and feed the normal goal audit.  It must not invent parser output, substitute shared-smoke evidence, or convert partial closure into a release pass.

Required aggregate fields should distinguish at least:

- passed unit gates;
- blocked unit gates with blocker IDs;
- failed unit gates;
- missing raw, registered, parsed, or adjudicated stage files;
- source-flow-plan blockers, including missing source flows, manifest identity mismatches, and reused source-flow directories;
- not-adjudicated units;
- candidates with all eight kernels passed;
- candidates still blocked from release eligibility.

The aggregate runner can make the Wave33 36×8 state easier to inspect, but final deliverable completion remains blocked until the independent full-system release/goal claim gate passes.

Wave34 source-flow-plan probe
`runs/dse/ralph_wave34_source_flow_plan_probe_expected_files_20260520T023516Z` currently
enumerates all 288 units and reports 280 missing source-flow rows plus 8 rows
blocked by missing release-candidate IDs in the source manifests.  Those 8 rows
came from the previous one-candidate smoke-flow map and must be regenerated or
restamped with exact release `candidate_id` provenance before materialization;
they cannot be copied into other candidates.

Wave35 therefore starts with source-flow-map closure, not raw materialization.
The lane objective is a complete 36 × 8 `source_flow_map.json` whose `flows[]`
rows carry exact `candidate_id`, `kernel_id`, and `source_flow_dir` values.  The
target source directory for each row must contain a `manifest.json` stamped with
the same release candidate and kernel.  Candidate-id-stamped manifests are the
handoff contract between RTL/HLS source-flow generation and Step5; old
kernel-only manifests remain diagnostic history and should be reported as
`source_flow_candidate_id_missing`.

The required Wave35 ordering is fail-closed:

1. generate or stage candidate/kernel source-flow directories with stamped
   `manifest.json` files;
2. assemble `source_flow_map.json` for the 288 intended bindings;
3. run `build_dft_hardware_closure_source_flow_plan.py`;
4. inspect `dft_hardware_closure_source_flow_plan_validation.json` and
   `dft_hardware_closure_source_flow_plan_status.json`;
5. materialize only rows whose `dft_hardware_closure_source_flow_plan.json`
   row has `source_flow_present=true` and `materialization_eligible=true`;
6. then run raw transcript registration, evidence intake, parser output,
   parsed-evidence manifest refresh, gate adjudication, release gate, trial
   ledger, final report, and goal audit.

Do not skip from a generated source directory directly to a pass claim.  Source
flows and source-flow plans are pre-materialization provenance only; they do not
prove golden correctness, simulation, synthesis, Vivado, DC, PPA, release, or
deliverable completion.

Wave35 produced 288 candidate-stamped local source-flow directories for the
36-candidate × 8-kernel matrix, but those directories are not hard-gate
completion.  Treat them as source-flow presence/provenance until each row is
selected, source-flow-planned, materialized, transcript-registered, parsed,
adjudicated, and release-gated.  A local source-flow directory without those
later artifacts must not be counted as PPA, candidate eligibility, or
deliverable completion.

Wave36 introduces the runner
`dse_v2/scripts/dse/run_dft_hardware_closure_real_source_flows.py` backed by
`dse_v2/reference_workloads/dft_hardware_closure_real_source_flow_run.py`.
It selects units from `dft_hardware_closure_packet_index.json`, runs the
per-kernel RTL flow with `--candidate-id` on `ssh_target=ic-eda` unless
`--skip-remote` is set, passes a candidate/run/kernel-scoped `--remote-dir` to
avoid remote scratch-directory collisions, and writes
`dft_hardware_closure_real_source_flow_run.json`, validation/status JSON,
`source_flow_map.json`, and
`source_flows/<candidate>/<kernel>/...`.  The runner's own adjudication stays
`not_adjudicated_by_real_source_flow_run` with `passed_stage_count=0`,
`hardware_completion_eligible=false`, and `deliverable_complete=false`.

Parallel lanes may be summarized with
`dse_v2/scripts/dse/build_dft_hardware_closure_latest_source_flow_map.py`.
That helper is a source-flow map assembly/discovery helper only: it scans
completed `wave36_real_source_flow_run_*_all8_*` roots, includes only runs whose
manifest is `source_flows_ready_pending_step5` with `source_flow_ready_count=8`
and `blocked_unit_count=0`, writes `discovery_status.json`, and then rebuilds a
canonical `source_flow_map.json`.  Ready count should be reported from
`discovery_status.included_run_count` and `included_runs[].candidate_ids`, while
map completeness should be reported separately from `source_flow_mapped_count`
and `source_flow_missing_count`.  Excluded runs and blocker IDs such as
`run_status_not_source_flows_ready_pending_step5`,
`source_flow_ready_count_not_8`, `blocked_unit_count_not_0`,
`candidate_id_filter_mismatch`, or claim-upgrade blockers are scheduling
signals, not errors to hide.  A partial latest map is still blocked for missing
candidate×kernel rows and must not be called release-complete.

The companion queue planner
`dse_v2/scripts/dse/plan_dft_hardware_closure_next_source_flow_batch.py` is
also fail-closed and non-executing.  It reads the packet index plus existing
ready/running run roots, writes `next_source_flow_batch.json`, and optionally
writes a review-only `next_source_flow_batch.sh`.  If the packet index is
invalid, if all candidates are already ready, or if no candidate should be
launched, the plan must contain no runnable EDA commands; the shell script is a
no-op.  Its `commands[]` are scheduling suggestions only and keep
`hardware_completion_eligible=false` and `deliverable_complete=false`.

Earlier Wave36 evidence was candidate-scoped.  The run
`runs/dse/wave36_real_source_flow_run_cand_0715923dc14b29cd_all8_20260520T033600Z`
made all eight kernels for `cand_0715923dc14b29cd`
`source_flow_ready_pending_step5`.  The filtered Step5 run
`runs/dse/wave36_step5_real_source_flow_cand_0715923dc14b29cd_all8_20260520T034024Z`
then reported `parsed_result_written_count=40`,
`stage_gate_passed_count=40`, `unit_gate_passed_count=8`,
`candidate_gate_passed_count=1`,
filtered `hardware_completion_eligible=true`, and
`deliverable_complete=false`.

The current strict checkpoint is the all-288 Step5 run
`runs/dse/wave36_step5_real_source_flow_all288_20260520T061902Z`.  It reports
36 candidates × 8 kernels = 288 gated units with
`stage_gate_passed_count=1440`, `unit_gate_passed_count=288`,
`candidate_gate_passed_count=36`, `source_flow_present_count=288`, and
`source_flow_missing_count=0`.  This closes the hardware-release-gate
eligibility checkpoint only: `dft_hardware_closure_release_gate.json` has
`hardware_completion_eligible=true` and `deliverable_complete=false`, while
`dft_scf_hardware_goal_completion_audit.json` remains `status=in_progress`.
The same run also carries the current-goal L4 bridge under
`current_goal_l4_bridge/`.  The bridge status is
`passed_identity_bridge_ready_for_regenerated_l4` with 36 candidates, six SCF
workloads, an exact structured crosswalk, and 216 expected regenerated L4 rows.
The regenerated root `runs/dse/current_goal_l4_regenerated_36x6_20260520T091000Z`
now executes that 36 × 6 shape: 216/216 row-level `gem5_l4_proof.json` files are
present and pass, and the rebuilt Step5 L4 binding is
`passed_current_goal_l4_bound`.  This closes the software-visible L4 transport
proof lane only; trusted speedup and deliverable completion remain blocked by
QE baseline/correctness/reference gates.  Its `legacy_9x4_crosswalk_assessment`
remains `insufficient_for_current_goal`; old 9 × 4 L4 mappings cannot satisfy
this 36 × 6 goal.

Parallel lanes must avoid evidence reuse by construction.  A lane owns one
candidate/kernel binding and must not point another row at the same
`source_flow_dir`, copy a passing `manifest.json` between candidates, reuse one
kernel's flow for another kernel, or use IC/EDA tool availability output as
source-flow or PPA evidence.  Expected blockers include
`blocked_reused_source_flow_count`,
`blocked_wrong_candidate_reuse_count`, `blocked_wrong_kernel_reuse_count`,
`blocked_invalid_manifest_count`, `provenance_mismatch_count`, and
`source_flow_candidate_id_missing`; these are safety signals, not paperwork to
silence.

## 7. Current-goal L4 proof/binding and QE reference lanes

The current-goal L4 lane now has both a bridge/provenance handoff and a
regenerated transport proof root.  The bridge owns these artifacts under the
Step5 run:

- `current_goal_l4_bridge/dft_current_goal_l4_bridge.json`;
- `current_goal_l4_bridge/current_goal_l4_crosswalk.json`;
- `current_goal_l4_bridge/dft_current_goal_l4_bridge_status.json`;
- `current_goal_l4_bridge/current_goal_l4_root/current_goal_l4_pending_root_manifest.json`;
- `current_goal_l4_bridge/current_goal_l4_root/l4_evidence_matrix.json`;
- `current_goal_l4_bridge/current_goal_l4_root/gem5_preflight.json`.

Safe summary for the latest L4 state: 36 × 6 bridge ready with exact structured
candidate/workload crosswalk; regenerated root
`runs/dse/current_goal_l4_regenerated_36x6_20260520T091000Z`; 216/216
row-level gem5 L4 transport proofs present and passed; Step5 binding
`passed_current_goal_l4_bound`; old 9 × 4 crosswalk insufficient.  Do not
summarize this as QE reference evidence, trusted speedup evidence, FPGA/ASIC PPA
evidence, or deliverable completion.

The local QE reference lane currently has two results.  The QE 6.7 probe
`runs/dse/dft_scf_six_class_local_qe_probe_20260520T074735Z/` found local
pseudos for every required element and copied their hashes into the bundle, but
all six `/usr/bin/pw.x` reference runs failed fail-closed (mostly SIGABRT/returncode
`-6`, with OpenMPI-aborted returncode `1` rows for the slow slab/projector cases).  The tuned QE 7.5 lane
`runs/dse/dft_scf_six_class_qe75_reference_tuned_20260520T085312Z/` uses the
repo-local `runs/dse/_tools/q-e-build/bin/pw.x`, records reference hashes only
when both `JOB DONE` and `convergence has been achieved` are present, and now
passes admission for all six classes with `blocker_count=0`.  It also emits one
layered workload profile per class under `workload_profiles/`.  The safe summary
is “L4 transport proof is present/bound; QE 6.7 is blocked; QE 7.5 tuned six-SCF
reference characterization is passed; final hardware/PPA, trusted speedup, and
deliverable gates remain open.”

## 8. ASIC gate reminder for parallel lanes

Every ASIC lane must produce candidate/kernel-specific Design Compiler evidence from a real target-library run and must include the packet-required `dc_synth.ddc`.  `dc_shell.log`, `dc_stdout.log`, `dc_timing.rpt`, `dc_area.rpt`, QoR summaries, or mapped Verilog without `dc_synth.ddc` are diagnostic blockers only.  They may explain why a lane is blocked; they must not be counted as ASIC pass evidence.

## 9. Docs and manual sync

Keep this supplement aligned with the active design manual and reporting docs when contracts change. Documentation work should remain descriptive and fail-closed:

- update manuals in the same iteration as artifact, schema, gate, or report contract changes;
- name exact artifacts and statuses when describing evidence flow;
- keep generic control-plane behavior separate from DFT plugin/profile policy;
- prefer `step2_screenable`, `step3_evaluable`, `simulation_eligible`, and `simulation_blockers` over stale ambiguous labels;
- document removed or replaced legacy names instead of silently dual-writing them.
- for WS6 edits, state whether a field belongs to applicability, stable design
  identity, evaluation/promotion policy, release/exploratory policy,
  feature-derived coverage, or fail-closed reference admission.

This file does not replace the main DFT/QE full-SCF hardware DSE design manual. It is a concise planning overlay for parallel execution and completion discipline.

## 10. Verification and anti-downgrade gates

Before any stronger claim, verify:

1. the 36 × 8 matrix has explicit candidate/kernel unit rows;
2. `source_flow_map.json` has one intended row per release candidate/kernel binding and each row's `manifest.json` stamps the same `candidate_id` and `kernel_id`;
3. each release candidate has eight required kernel rows or explicit host-bound cost rows;
4. source-flow planning, raw materialization, raw transcript registration, parser, gate adjudication, release rollup, and trial-ledger artifacts are visible where applicable;
5. all referenced evidence paths stay under the evidence root and match candidate/kernel identity;
6. FPGA claims have Vivado synthesis/implementation evidence and ASIC claims have DC synthesis/timing/area evidence from a real target-library run plus `dc_synth.ddc`;
7. host-bound work includes synchronization, transfer, control, diagonalization, mixing, convergence, and I/O costs where applicable;
8. search reports separate seeds, exploratory rows, release-tier rows, and trusted evidence-eligible rows;
9. IC/EDA availability artifacts are reported as availability-only, not source-flow or PPA evidence;
10. real source-flow runner artifacts are reported as execution/provenance, not
    hard-gate adjudication by themselves;
11. latest source-flow map auto-discovery is reported as ready-root discovery and
    map assembly only; partial maps with missing rows remain blocked;
12. the current-goal L4 bridge plus regenerated root are treated as
    software-visible 36 × 6 transport proof only; they do not close QE,
    correctness, speedup, FPGA/ASIC PPA, or deliverable gates by themselves;
13. local six-SCF QE probes split QE 6.7 fail-closed blockers from the tuned QE 7.5
    convergence-gated hash lane, and no row hash is final without both `JOB DONE`
    and verified SCF convergence;
14. layered workload profiles expose `kernel_workload_graph.kernel_gate_contracts`
    for every required workload gate, but these contracts remain metadata and do
    not replace candidate/kernel evidence rows;
15. WS6 artifacts keep applicability/offload scope, stable design identity,
    evaluation policy, and release policy as separate verdict/metadata fields;
16. coverage vectors derive required gates from facts/features, not manual
    `stress_tags`;
17. final QE reference admission fails closed for hash-only or
    non-converged/non-local output material;
18. `dft_audit_semantic_closure.json` is present, source-hash backed, and
    passes all five semantic sections before the goal audit can clear the HIGH
    semantic findings;
19. the goal audit remains `in_progress` until the full-system release gate says otherwise.

Anti-downgrade rule: do not convert a vertical slice, fixed seed set, model-level run, h_psi-only proof, materialized-only packet set, or partially registered matrix into a deliverable-complete DFT/QE full-SCF hardware DSE claim.
