# DFT/QE Full-SCF Hardware DSE Design Manual

**Status:** design manual seed / not execution-complete
**Primary source:** `docs/dse_instruction.md`
**Planning artifact:** `.omx/plans/dft-scf-hardware-dse-codesign-master-plan-20260519T062553Z.md`
**Active HIGH-fix plans:** `.omx/plans/prd-dft-workload-profile-high-fixes-20260520T102113Z.md`;
`.omx/plans/prd-dft-audit-high-fix-ralplan-20260520T165732Z.md`

## Current strict state (2026-05-20)

- The workload front door is a six-class SCF descriptor-plus-runnable bundle
  contract.  Synthetic fixture/pseudo material is admission scaffolding only;
  real QE reference outputs remain a separate proof requirement.
- The first prototype boundary is **full-SCF evaluated hybrid**: host-bound
  I/O, SCF control, convergence, diagonalization, mixing, transfer,
  synchronization, queueing, and layout costs stay in end-to-end accounting and
  are not hardware acceleration benefits.
- Per-kernel acceleration claims are strict.  Each claimed candidate/kernel row
  must pass golden correctness, HLS C-sim or RTL sim, HLS C-synth or RTL synth,
  plus Vivado implementation for FPGA claims and DC target-library
  synthesis/timing/area with `dc_synth.ddc` for ASIC claims.
- The latest all-288 checkpoint
  `runs/dse/wave36_step5_real_source_flow_all288_20260520T061902Z` reaches
  hardware release-gate eligibility for 36 candidates × 8 kernels
  (`unit_gate_passed_count=288`, `candidate_gate_passed_count=36`,
  `hardware_completion_eligible=true`) but still has
  `deliverable_complete=false`.
- Current-goal L4/gem5 transport proof is now present and bound for the
  36-candidate × 6-SCF target.  The bridge under
  `runs/dse/wave36_step5_real_source_flow_all288_20260520T061902Z/current_goal_l4_bridge/`
  remains the provenance/crosswalk handoff, while the regenerated proof root
  `runs/dse/current_goal_l4_regenerated_36x6_20260520T091000Z` contains
  216/216 `gem5_l4_proof.json` files with `passed=true`.  The Step5 binding
  status has `status=passed`, `binding_status=passed_current_goal_l4_bound`,
  `current_goal_l4_bound=true`, and `l4_software_visible_proof_present=true`.
  This is software-visible L4 transport proof only: the L4 report and final
  deliverable remain blocked by QE baseline/correctness/reference gates, and the
  old 9 × 4 crosswalk is still insufficient for the current 36 × 6 goal.
- The QE reference lane is split.  The QE 6.7 `/usr/bin/pw.x` probe
  `runs/dse/dft_scf_six_class_local_qe_probe_20260520T074735Z` found all
  required local pseudopotentials but failed fail-closed (mostly SIGABRT/returncode
  `-6`, with OpenMPI-aborted returncode `1` rows for the slow slab/projector
  cases), so it provides no final hashes.  The tuned QE 7.5 lane
  `runs/dse/dft_scf_six_class_qe75_reference_tuned_20260520T085312Z` uses the
  repo-local `runs/dse/_tools/q-e-build/bin/pw.x`, reuses/records hashes only
  when both `JOB DONE` and `convergence has been achieved` are present, and now
  has `status=passed`, `admitted=true`, `case_count=6`, and `blocker_count=0`.
  It also materializes `workload_profiles/*_workload_profile.json` for the new
  layered Step1 DFT workload analysis.  This is converged Step1 QE reference
  characterization, not hardware/PPA evidence or deliverable completion.
- The current workload/profile/audit HIGH-fix tranche has a tested canonical
  split for workload applicability/offload scope, stable design candidate
  identity, evaluation/promotion policy, release/exploratory queue policy,
  feature-derived coverage, and fail-closed QE reference admission.  Fresh
  evidence for this tranche is `python3 -m pytest -q dse_v2/tests` passing,
  `python3 -m compileall -q dse_v2` passing, and the DFT stale-term scanner
  reporting `authoritative_stale_count=0`.  This tranche still must not be
  summarized as full HLS/RTL/FPGA/ASIC PPA closure or final DFT/QE hardware DSE
  completion.

## 1. Claim boundary

The target is **DFT/QE full-SCF evaluated hardware DSE and co-design**, not a full-SCF device-resident accelerator in the first prototype.

The generic DSE control plane remains domain-neutral. DFT-specific facts belong in workload descriptors, runnable bundles, hardware candidate templates, profile adapters, evidence schemas, and reporting gates.

Forbidden final claims:

- h_psi-only evidence is not full-SCF closure;
- SystemC/gem5 model-level evidence is not final hardware DSE closure;
- exploratory candidates are not trusted Pareto/frontier entries;
- host-bound CPU work is not hardware acceleration benefit;
- DC-only evidence is not an FPGA claim gate;
- Vivado-only evidence is not an ASIC claim gate.

## 2. Workload input contract

A workload is admitted only as a **strict closure bundle**:

- normalized DFT descriptor;
- QE input files;
- pseudopotentials;
- run command/environment;
- reference outputs or hashes;
- provenance/license notes;
- parser/tool versions;
- declared proof-class label.

Profiling traces and phase timing are required for calibration/analysis, but they may be attached after admission.

The frozen suite must cover six SCF classes.  The canonical code identifiers
are:

1. `small_multi_k_scf` — small multi-k silicon-style SCF;
2. `metal_smearing_scf` — metallic/smearing SCF;
3. `insulator_scf` — insulating SCF baseline;
4. `slab_vacuum_large_fft_scf` — slab/vacuum case stressing large FFT and
   layout traffic;
5. `gamma_only_supercell_scf` — gamma-only supercell case;
6. `projector_orthogonalization_heavy_scf` — projector/orthogonalization-heavy
   case.

`dse_v2.codesign.dft_scf_workstreams.STRICT_DFT_QE_WORKLOAD_CLASSES` is the
implementation source for these identifiers.  Human-readable labels may appear
in reports, but admission and regression tests should use the canonical IDs.

### 2.1 DFT workload analysis layering

The six SCF classes are a **reference suite selection**, not the workload
analyzer itself.  Step1 DFT/QE analysis is now represented by
`dse_v2/reference_workloads/dft_workload_profile.py` and must keep these layers
separate:

1. `source_bundle` — QE input path/hash, pseudopotential refs, run command,
   reference-output ref, parser version, proof class, provenance/license;
2. `raw_input_facts` — facts parsed directly from the QE deck: calculation,
   structure/cell/atoms/species, `ecutwfc`, optional `ecutrho`, occupations,
   smearing, explicit `nbnd`, spin flags, electron controls, and k-point mode/grid;
3. `resolved_run_facts` — facts confirmed by QE output or marked missing/input
   estimated: resolved `nbnd`, k-point counts, per-k `npw`, FFT grid, valence
   electrons, projector count, SCF iterations, warnings, and confidence labels;
4. `derived_scale_features` — FFT/Hψ/projector/dense-linear-algebra/reduction/
   host-device pressure estimates derived from raw/resolved facts;
5. `coverage_vector` — machine-readable pressure axes and
   `required_kernel_gates`; legacy display `stress_tags` may remain but must not
   be the gate driver;
6. `kernel_workload_graph` — DFT-scoped SCF kernel summary graph feeding Step2
   architecture/mapping legality, with `domain_physics_correctness_claimed=false`;
7. `reference_suite_case` — case selection role and strict-suite coverage.

This boundary prevents `ecutwfc`/cell/k-point raw facts, QE-resolved `npw`/`nfft`,
pressure labels, benchmark-suite membership, candidate parameters, and evidence
policy from collapsing into one ambiguous “workload parameter” bag.  It also
keeps DFT/QE fields inside the reference profile/plugin layer rather than the
domain-neutral generic core.

Reference rationale for the manual: QE `pw.x` input documentation separates raw
namelist/block inputs from values later resolved by initialization/output
(<https://www.quantum-espresso.org/Doc/INPUT_PW.html>); QE parallelization
options such as pools/task groups are reference-execution configuration rather
than workload identity (<https://www.quantum-espresso.org/Doc/user_guide/node20.html>);
AiiDA provenance and atomate2/jobflow-style workflow abstractions motivate
keeping source/provenance and package-specific adapters distinct from generic
workflow semantics; Timeloop/MAESTRO and Ansor motivate separating workload,
architecture, mapping, schedule, and feedback/search policy.

The concrete descriptor-plus-runnable fixture slice is materialized by
`dse_v2/scripts/dse/build_dft_scf_six_class_bundle.py`.  It writes
`dft_scf_six_class_bundle_manifest.json`, per-class descriptors, generated QE
input decks, synthetic pseudo placeholder files with hashes, and run scripts.
By default the manifest is fail-closed with
`blocked_missing_real_reference_output_hashes`: no placeholder QE reference
output hash is fabricated, and the synthetic fixture/pseudo material is not
final real QE evidence or hardware/PPA evidence.

QE 6.7 local probe: `runs/dse/dft_scf_six_class_local_qe_probe_20260520T074735Z`
used local pseudo discovery under `/usr/share/espresso/pseudo` and found all
required elements (`Al`, `C`, `O`, `Se`, `Si`, `Ti`, `W`).  It attempted all
six `/usr/bin/pw.x` runs with a 45-second bound, but the Ubuntu QE 6.7 binary
failed fail-closed (mostly SIGABRT/returncode `-6`, with OpenMPI-aborted returncode `1` rows for the slow slab/projector cases); `hash_final=false`,
`sha256=null`, `reference_output_hash_manifest.complete=false`,
`final_real_qe_evidence=false`, and `deliverable_complete=false`.  These local
pseudos are useful input material only; the QE 6.7 probe does not provide real
QE reference hashes.

QE 7.5 tuned reference lane:
`runs/dse/dft_scf_six_class_qe75_reference_tuned_20260520T085312Z` uses the
repo-local `runs/dse/_tools/q-e-build/bin/pw.x` and the same local pseudo
directory.  The bundle builder is fail-closed: a zero return code is
insufficient; reference hashes are recorded only for rows whose output has both
`JOB DONE` and `convergence has been achieved`.  The tuned bundle now has
`status=passed`, `admitted=true`, `case_count=6`, `local_qe_reference_run_complete=true`,
and `blocker_count=0`; all six reference outputs have convergence-gated SHA-256
hashes and the manifest contains the new `workload_analysis_model`.  Each case
also has a `workload_profile` artifact under `workload_profiles/` with exact QE
resolved `npw`, `nfft`, `nbnd`, and k-point confidence where QE output reports
those facts.  This closes the Step1 six-SCF reference-characterization lane, but
it still does not close hardware acceleration, trusted speedup, FPGA/ASIC PPA,
or deliverable-complete gates.

### 2.2 Feature-derived coverage-vector policy

Coverage is a fact-derived Step1 output, not a manual tag contract.  The
canonical coverage vector derives `required_kernel_gates` from:

- `raw_input_facts`, such as calculation kind, k-point mode/grid, `ecutwfc`,
  optional `ecutrho`, occupations/smearing, explicit `nbnd`, spin flags, and
  cell/atom/species facts;
- `resolved_run_facts`, such as resolved `nbnd`, resolved k-point counts,
  per-k `npw`, FFT grid, valence electrons, projector count, SCF iterations,
  warnings, and confidence labels;
- `derived_scale_features`, such as `nfft_total`, resolved `nfft`, projector
  pressure, band/dense-linear-algebra pressure, dot products per SCF estimate,
  transfer bytes per SCF estimate, and SCF-kind pressure.

Manual `stress_tags` may remain only as display/suite-intent annotations.  They
must not add or remove `required_kernel_gates`.  The coverage vector should
carry `gate_derivation_reasons` so every required gate can be traced to concrete
facts or thresholds.  If a fact needed for a gate is missing, the profile should
emit a confidence/blocker field instead of silently dropping the gate.

### 2.3 Fail-closed QE reference admission

Final real-QE admission requires source-backed local or reused QE output.  A
caller-supplied hash without an admitted output file is provenance only and must
not set `final_real_qe_evidence` or a final proof class.

A final admitted six-class case must satisfy all of these checks:

- `reference_output.sha256` exists and `reference_output.hash_final is True`;
- `reference_output.path` resolves to an existing local or reused converged QE
  output under the bundle;
- `reference_summary.raw_output_sha256 == reference_output.sha256`;
- `reference_summary.convergence_verified is True`;
- `reference_summary.normalized_reference_summary_hash` exists;
- the proof class distinguishes local/reused converged QE output from
  caller-supplied hash-only material.

The admission rule is intentionally stricter than hash presence.  It protects
Step1 characterization and later Step5 claim reports from treating external or
hash-only material as final real-QE evidence.

## 3. Candidate space

Use multiple hardware template families:

- streaming FFT-Hψ;
- projector-heavy;
- memory/HBM-rich;
- hybrid CPU-FPGA;
- ASIC tile/template.

Candidate queue policy is two-tier metadata, not a Step2 search dimension:

- release lane: conservative, synthesizable, eligible for formal Pareto only after evidence gates;
- exploratory lane: wider search, isolated from trusted claims until promoted;
- `seed_source`: literature or existing FPGA-HBM/FFT/NoC/HLS designs should seed initial ranges where possible.

### 3.1 Canonical split: applicability, design, evaluation, release

Candidate records must keep four policy layers separate:

1. **Workload applicability / offload scope** — `dft_phase_hotspot_selection`
   and any compatibility alias such as offload-scope selection describe which
   SCF phases/hotspots a row applies to.  This may change
   `applicability_assignments`, compatibility blockers, and queue routing, but
   it must not change stable design identity, design legality, or design score.
2. **Stable design candidate identity** — `design_candidate_id` hashes only
   design semantics such as algorithm variant, schedule/runtime policy,
   mapping/data layout, hardware microarchitecture, and interface/descriptor
   protocol.  It excludes workload IDs, workload-case IDs, phase/hotspot
   applicability, evidence fidelity/promotion policy, release/exploratory queue
   policy, retry/tool status, and claim labels.
3. **Evaluation / promotion policy** —
   `evidence_fidelity_promotion_policy` belongs in
   `evaluation_policy_assignments`, promotion requirements, or evaluation-row
   metadata.  It schedules and gates evidence, but it does not make a design
   legal/illegal and does not contribute to the design score.
4. **Release / exploratory queue policy** — release eligibility and
   exploratory isolation are policy metadata.  The legacy candidate-tier field
   must not be a Step2 search parameter or part of candidate identity.  Formal Pareto/release
   filters should consume DFT policy metadata such as release-template
   membership, precision legality, and `formal_pareto_eligible`.  Downstream
   trial ledgers may expose a derived lane in audit rows, but they must not
   persist legacy release-lane aliases inside Campaign/Trial `params_json` or nested
   candidate parameter maps.

For compatibility, the seven-axis release preset may retain `candidate_id` as a
unique all-axis evaluation-row key so older artifacts stay addressable.  That
key is not the stable hardware design identity.  Rows that differ only by
phase/hotspot applicability, evidence policy, or release/exploratory queue
metadata must share the same `design_candidate_id` when their design semantics
are otherwise identical.

Current status: this split is implemented for the HIGH audit tranche and locked
by tests/scanner.  It remains a boundary/schema correctness milestone, not a
hardware PPA or final completion claim.

## 4. Search policy

The first search path is **hierarchical funnel search**:

1. template-family enumeration and legality checks;
2. analytic SCF cost-model rough screening;
3. bottleneck-guided local refinement;
4. small HLS/RTL/PPA calibration batch;
5. Pareto/frontier reporting only for evidence-eligible candidates.

Later NSGA-II, BO/EHVI, ensemble, or MCTS search can be added as plugins, but
they must use the same release/exploratory policy metadata and evidence
contracts without reintroducing legacy candidate-tier data as a search
parameter.

Implementation status:

- `dse_v2.mapping.search_policy.HierarchicalFunnelSearchPolicy` is the
  domain-neutral staged policy.  It records the five funnel stages, consumes
  generic parameter grids/seeds, and prevents non-release-lane candidates from
  entering formal Pareto eligibility.
- `dse_v2.reference_workloads.dft_step2_policy` owns the DFT/QE template
  mapping.  Its initial release families are
  `streaming_fft_hpsi_pipeline`, `projector_heavy_gemm_gemv`,
  `memory_hbm_dma_transpose`, `hybrid_cpu_fpga_scf_sidecar`, and
  `asic_tile_array_template`.  `wide_exploratory_noc_hls_variants` is
  exploratory only.
- `dse_v2/scripts/dse/build_dft_seven_axis_release_artifacts.py` now emits
  `hierarchical_funnel_search_report.json` alongside the seven-axis release
  artifacts.  This report may order future evidence work, but it is not trusted
  Pareto/speedup/completion evidence.

Latest Ralph Wave-4 artifact example:

```text
runs/dse/ralph_wave4_dft_hierarchical_search_artifacts_20260519T105437Z/
  hierarchical_funnel_search_report.json
  seven_axis_search_space_report.json
  candidate_universe_manifest.json
```

In that run, all five release template families were present in the formal
release queue and exploratory rows remained excluded from formal Pareto.

## 5. Claimed-kernel evidence gates

If a candidate claims acceleration for any of these kernels, that kernel must pass the full claim-type gate:

- FFT / iFFT / fFFT;
- 3D transpose / layout conversion;
- Hψ local potential path;
- kinetic add;
- nonlocal projector;
- complex GEMM / GEMV tile;
- reduction / dot-product tree;
- DMA / HBM movement engine.

Minimum promotion ladder:

```text
golden correctness
→ HLS C-sim or RTL sim
→ HLS C-synth or RTL synth
→ Vivado synth/implementation for FPGA claim
→ DC synthesis/timing/area for ASIC claim
```

A dual FPGA+ASIC claim must pass both tool branches.

The ASIC branch is a hard evidence contract, not a log-presence check.  An ASIC
pass requires a Design Compiler run against a real target library plus the
candidate/kernel-scoped `dc_synth.ddc` design database.  DC logs, timing
reports, area reports, QoR summaries, or mapped Verilog without that `.ddc` and
real target-library evidence are diagnostic blockers; they are not ASIC pass
evidence.

The DFT/QE major-kernel wrapper additionally requires an explicit row for all
eight kernels above.  A row may be:

- `accelerated_claim` with `claim_type` and kernel-scoped evidence rows;
- `host_bound` with `host_cost_accounted=true`, which counts cost but never
  supports acceleration;
- a blocker with concrete reason and next action.

Evidence is scoped by `kernel_id`.  Cross-kernel artifacts are ignored by the
claim validator and reported as `cross_kernel_evidence_ignored`; they cannot be
used to satisfy another kernel's gate.

Each Step1 layered workload profile now embeds machine-readable
`dse.dft.kernel_gate_contract.v1` entries under
`kernel_workload_graph.kernel_gate_contracts`.  A contract records the semantic
`gate_id`, legacy `kernel_id` alias when one exists, coverage triggers,
workload-shape fields, candidate requirements, L3/L4 evidence expectations,
FPGA/ASIC branch requirements, metrics, and pass/fail constraints.  These
contracts are workload/search interface metadata only; they do not assert that a
candidate has passed any gate.

## 6. First prototype boundary

The first prototype is **full-SCF evaluated hybrid**:

- hardware claims: FFT/transpose/Hψ/projector/reduction/DMA only when gates pass;
- CPU keeps: I/O, input parsing, SCF control, convergence checks, diagonalization, mixing;
- mandatory cost accounting: host-bound compute, synchronization, host-device transfer, queueing, launch overhead, and layout conversion outside accelerated paths.

Do not report full-SCF speedup by hiding host-bound or transfer costs. Report kernel-level speedups separately from end-to-end SCF evaluated speedup.


### Descriptor/cost helper contract

`dse_v2.reference_workloads.dft_full_scf_hybrid` provides the DFT-scoped
machine-readable descriptor/cost helper for this first prototype boundary.  It
is intentionally outside the domain-neutral core and fails closed unless the
payload includes:

- accelerated-kernel schedule pieces for the eight major SCF kernel IDs;
- host-bound cost pieces for `io`, `scf_control`, `convergence`,
  `diagonalization`, and `mixing`;
- runtime overhead cost pieces for `transfer`, `synchronization`, `queueing`,
  and `layout`.

Host-bound and overhead pieces must carry `hardware_acceleration_claim=false`.
Any acceleration claim outside the eight major kernel IDs is invalid, and the
payload remains descriptor/cost evidence only; it is not a full-SCF completion
claim or a substitute for HLS/RTL/FPGA/ASIC gates.

The helper writes the Wave-4 evaluated-hybrid artifact bundle:

- `full_scf_accelerator_descriptor.json`;
- `full_scf_runtime_schedule.json`;
- `full_scf_data_residency_plan.json`;
- `full_scf_correctness_report.json`;
- `full_scf_ppa_summary.json`.

These artifacts are DFT-profile artifacts, not generic core contracts.  Step5
may cite them under `dft_full_scf_evaluated_hybrid` and may use the descriptor
cost model to populate `full_scf_evaluated_hybrid_costs`, but the report must
keep `completion_claim=false`, `numerical_correctness_claim_eligible=false`,
and `ppa_claim_eligible=false` until independent correctness and Vivado/DC
gates pass.

Replayable bundle creation uses explicit cost JSON files rather than hidden
defaults:

```bash
python3 dse_v2/scripts/dse/build_dft_full_scf_hybrid_bundle.py \
  --out runs/dse/<full_scf_hybrid_bundle> \
  --candidate-id <candidate_id> \
  --campaign-id <campaign_id> \
  --workload-run-id <workload_run_id> \
  --trial-id <trial_id> \
  --accelerated-kernel-costs-json <accelerated_kernel_costs.json> \
  --host-bound-costs-json <host_bound_costs.json> \
  --overhead-costs-json <overhead_costs.json> \
  --baseline-scf-time-s <optional_baseline_seconds>
```

## 7. Completion discipline

Completion requires strict workload bundles, realistic candidate generation, claim-specific evidence gates, full-SCF evaluated reporting, and docs kept synchronized with code/schema/evidence changes. Intermediate green tests or runnable demos are progress only unless every final gate is satisfied.

## 8. RALPLAN workstream governance addendum

The approved follow-up plan adds an integration-governance lane before broad implementation.

### Lane J — Integration Spine & Contract Governance

Lane J owns the canonical schema/ID/contracts that allow workload, search, tool, evidence, report, and documentation lanes to compose:

- artifact/schema registry and versioning;
- strict bundle contract;
- candidate/release-policy contract;
- evidence/adjudication/report handoff contract;
- `campaign_id`, `workload_run_id`, `trial_id` propagation;
- release/exploratory isolation;
- migration/deprecation policy;
- cross-lane compatibility tests.

### Wave 1.5 thin trace

Before broad HLS/RTL/tool/kernel work scales out, the system must run a progress-only thin trace:

```text
strict workload bundle
→ release-policy DMA/HBM or transpose candidate
→ tool transcript or blocker
→ Step4 adjudication
→ Step5 report
```

This trace validates the integration spine only. It must not be reported as final completion.

Replayable fixture/runbook generation:

```bash
python3 dse_v2/scripts/dse/build_dft_wave15_trace.py \
  --out runs/dse/<wave15_trace_run>
```

The command writes:

- `strict_workload_bundle.json`;
- `release_candidate.json`;
- `tool_evidence.json`;
- `wave15_trace.json`;
- `wave15_summary.json`;
- `wave15_runbook.md`.

The default fixture deliberately records a Vivado blocker for the tool branch,
so `wave15_trace.json` should have `status=blocked_progress_only`,
`completion_claim=false`, and `mvp_claim=false`.  Supplying custom
`--strict-bundle-json`, `--release-candidate-json`, or `--tool-evidence-json`
is allowed, but the trace remains a pressure test until the downstream
all-candidate and per-kernel gates close.

### Reporting invariants

Step5 must report kernel speedup separately from end-to-end SCF evaluated speedup and include host-bound, transfer, synchronization, queueing, and layout costs.  Formal Pareto/frontier excludes exploratory, model-only, blocked, fake-PPA, and wrong-claim-type candidates.

When the full-SCF evaluated-hybrid bundle is present directly in the Step5 run
directory, or is attached indirectly through the DFT evidence ledger's
`full_scf_hybrid_bundle.artifact_refs`, Step5 also reports:

- descriptor/prototype boundary and host-orchestrated device residency;
- accelerated kernel IDs, host-bound phase IDs, and runtime overhead IDs;
- descriptor validation status;
- numerical-correctness and PPA claim eligibility flags, both fail-closed until
  stronger evidence is attached;
- cost-model source (`full_scf_accelerator_descriptor.json` when descriptor
  costs are used).

If no explicit `kernel_speedup` is present in simulation metrics, Step5 may
derive an accounting-only kernel speedup from
`(baseline_scf_time_s - host_bound_cost_s) / accelerated_kernel_cost_s` and
must label it with
`kernel_speedup_source=derived_from_baseline_scf_minus_host_bound_cost`.
This derived value is for evaluated-hybrid reporting only; it is not a trusted
Pareto claim and does not replace per-kernel correctness/Vivado/DC gates.

If Step5 recovers the bundle through ledger refs, the report marks
`dft_full_scf_evaluated_hybrid.source =
dft_evidence_ledger.full_scf_hybrid_bundle` and resolves the external artifact
paths before using descriptor cost fields.  Unreadable ledger refs remain
visible but fail closed as partial bundle evidence.

### Wave 13 trial state ledger

`dse_v2.reference_workloads.dft_trial_ledger` adds the DFT-profile trial
state ledger that connects the search/evidence/report/audit chain without
moving DFT semantics into the generic control plane.  The replayable command is:

```bash
python3 dse_v2/scripts/dse/build_dft_candidate_binding_map.py \
  --out runs/dse/<binding_run> \
  --hierarchical-search-report runs/dse/<step5_run>/release_domain/hierarchical_funnel_search_report.json \
  --candidate-universe-manifest runs/dse/<step5_run>/release_domain/candidate_universe_manifest.json \
  --per-candidate-evidence-ledger runs/dse/<step5_run>/dft_ledger/per_candidate_evidence_ledger.json

python3 dse_v2/scripts/dse/build_dft_trial_state_ledger.py \
  --out runs/dse/<trial_ledger_run> \
  --hierarchical-search-report runs/dse/<step5_run>/release_domain/hierarchical_funnel_search_report.json \
  --per-candidate-evidence-ledger runs/dse/<step5_run>/dft_ledger/per_candidate_evidence_ledger.json \
  --eda-all-candidate-evidence runs/dse/<step5_run>/dft_ledger/eda_all_candidate_evidence.json \
  --candidate-binding-map runs/dse/<binding_run>/dft_candidate_binding_map.json \
  --final-report runs/dse/<step5_run>/final_report.json \
  --goal-audit runs/dse/<step5_run>/dft_scf_hardware_goal_completion_audit.json
```

The binding helper writes `dft_candidate_binding_map.json`,
`dft_candidate_binding_map_validation.json`, and
`dft_candidate_binding_map_status.json`.  This map is deliberately heuristic:
it relates hierarchical Step2 search IDs to frozen seven-axis release candidate
IDs for audit/resume and evidence-row lookup, but it is not numerical evidence,
trusted Pareto proof, FPGA/ASIC closure, or completion evidence.

Build the candidate × kernel hardware completion workplan after the binding map
and all-current kernel smoke artifacts are available:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_completion_workplan.py \
  --out runs/dse/<workplan_run> \
  --per-candidate-evidence-ledger runs/dse/<step5_run>/dft_ledger/per_candidate_evidence_ledger.json \
  --dft-hardware-evidence-matrix runs/dse/<kernel_matrix_run>/dft_hardware_evidence_matrix.json \
  --ic-eda-tool-availability runs/dse/<ic_eda_probe_run>/ic_eda_tool_availability.json \
  --candidate-binding-map runs/dse/<binding_run>/dft_candidate_binding_map.json
```

The workplan writes `dft_hardware_completion_workplan.json`,
`dft_hardware_completion_workplan_validation.json`, and
`dft_hardware_completion_workplan_status.json`.  It expands every release
candidate, each of the eight major kernels, and the required hard-gate stages:
golden correctness, HLS/RTL simulation, HLS/RTL synthesis, Vivado FPGA
synthesis/implementation, and DC ASIC synthesis/timing/area.  Shared
microkernel smoke evidence is recorded as useful input but remains blocked for
candidate-specific closure; no row can set `hardware_completion_eligible` or
`deliverable_complete`.

Shard the workplan into parallel closure queues for manual/agent assignment:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_shards.py \
  --out runs/dse/<closure_shards_run> \
  --hardware-completion-workplan runs/dse/<workplan_run>/dft_hardware_completion_workplan.json \
  --max-units-per-shard 16
```

The shard helper writes `dft_hardware_closure_shards.json`,
`dft_hardware_closure_shards_validation.json`, and
`dft_hardware_closure_shards_status.json`.  It groups candidate × kernel units
with required tools, stage IDs, work-item IDs, and blocked execution status.
Each queued unit still requires a candidate-specific RTL/HLS bundle plus real
tool execution before any evidence row can move out of blocked status.

Expand the shard queue into per-shard closure packets and runbooks before
assigning real hardware-closure work:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_packets.py \
  --out runs/dse/<closure_packets_run> \
  --hardware-closure-shards runs/dse/<closure_shards_run>/dft_hardware_closure_shards.json
```

The packet helper writes `dft_hardware_closure_packet_index.json`,
`dft_hardware_closure_packet_index_validation.json`,
`dft_hardware_closure_packet_index_status.json`, and one JSON packet plus one
Markdown runbook under `dft_hardware_closure_packets/` for each shard.  A
packet enumerates candidate IDs, kernel IDs, required stage/tool IDs, exact
expected candidate-specific evidence filenames, and command templates for
golden reference, VCS/HLS simulation, HLS/RTL synthesis, Vivado FPGA
synthesis/implementation, and DC ASIC synthesis/timing/area.  It remains
fail-closed: all packet and index rows keep
`candidate_specific_bundle_count=0`,
`candidate_specific_evidence_present_count=0`,
`hardware_completion_eligible=false`, and `deliverable_complete=false` until
real per-candidate/per-kernel bundles and raw tool outputs are attached by a
later closure lane.

Materialize the candidate-specific bundle templates referenced by the packets
before raw evidence intake:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_candidate_bundles.py \
  --out runs/dse/<closure_packets_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --evidence-root runs/dse/<closure_packets_run>
```

The bundle helper writes
`dft_hardware_closure_candidate_bundle_index.json`,
`dft_hardware_closure_candidate_bundle_index_validation.json`,
`dft_hardware_closure_candidate_bundle_status.json`, and one
`candidate_bundle.json` under each packet's
`candidate_specific_bundles/<candidate>/<kernel>/` path.  These bundles are
execution metadata and source/evidence placement contracts only: they name the
candidate, kernel, stage IDs, command-template IDs, and expected raw evidence
filenames.  They must keep `raw_evidence_file_count=0`,
`raw_evidence_present=false`, `adjudication_status=not_adjudicated_by_bundle`,
`hardware_completion_eligible=false`, and `deliverable_complete=false`.
Validation opens every referenced bundle, recomputes its hash, rejects payload
claim upgrades, rejects expected evidence rows that mark files present, and
rejects absolute or parent-traversal bundle paths.  If `--evidence-root` is
omitted, the helper uses the closure-packet index directory so the default root
matches the evidence-intake helper.

Stage candidate/kernel-scoped unit provenance after bundle templates and before
raw evidence intake:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_unit_provenance.py \
  --out runs/dse/<unit_provenance_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --evidence-root runs/dse/<closure_packets_run>
```

The unit-provenance helper writes
`dft_hardware_closure_unit_provenance_index.json`,
`dft_hardware_closure_unit_provenance_validation.json`,
`dft_hardware_closure_unit_provenance_status.json`, and per-unit metadata
files under each packet's candidate-specific evidence directory:
`tool_versions.json`, `command_manifest.json`, `raw_transcript_index.json`,
and `source_bundle_manifest.json`.  These files are **metadata/provenance
staging only**.  They do not contain VCS/HLS/Vivado/DC raw logs, parsed
results, PPA data, or hard-gate verdicts.  They must keep
`raw_stage_evidence_file_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`, and validation rejects path escape, hash
mismatch, candidate/kernel mismatch, embedded raw stage evidence, shared-smoke
scope, or any claim-upgrading flag.  A valid unit-provenance stage can unblock
parser readiness checks, but it cannot pass golden, simulation, synthesis,
Vivado, DC, PPA, Pareto, hardware-completion, or deliverable-completion gates.

To generate candidate-stamped source-flow directories from the packet index,
run the DFT-profile real source-flow runner before source-flow planning:

```bash
python3 dse_v2/scripts/dse/run_dft_hardware_closure_real_source_flows.py \
  --out runs/dse/<real_source_flow_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --candidate-id <release_candidate_id> \
  --jobs <parallel_jobs>
```

The runner selects candidate/kernel units from
`dft_hardware_closure_packet_index.json`, dispatches the matching per-kernel
RTL/HLS source-flow script with `--candidate-id`, and uses `--ssh-target
ic-eda` by default unless `--skip-remote` is set.  It also passes a
candidate/run/kernel-scoped `--remote-dir` to each kernel flow so parallel
candidate shards do not clobber remote `/tmp/dft_accelerate_*` work
directories.  It writes
`dft_hardware_closure_real_source_flow_run.json`,
`dft_hardware_closure_real_source_flow_run_validation.json`,
`dft_hardware_closure_real_source_flow_run_status.json`,
`source_flow_map.json`, and per-unit
`source_flows/<candidate>/<kernel>/...` directories.  This runner is
execution/provenance only:
`adjudication_result=not_adjudicated_by_real_source_flow_run`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false` must remain true.  A ready source-flow row can
feed source-flow planning; it cannot pass golden correctness, simulation,
synthesis, Vivado, DC, PPA, Pareto, hardware-completion, or
deliverable-completion gates by itself.

For rolling multi-candidate execution, build the latest ready source-flow map
from completed all-eight real-source-flow runs before source-flow planning:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_latest_source_flow_map.py \
  --out runs/dse/<latest_source_flow_map_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --run-root runs/dse
```

`--run-root` is repeatable and defaults to `runs/dse`; `--candidate-id` can
filter discovery.  The helper scans
`wave36_real_source_flow_run_*_all8_*/dft_hardware_closure_real_source_flow_run.json`
and includes only fail-closed ready runs with
`status=source_flows_ready_pending_step5`, `source_flow_ready_count=8`,
`blocked_unit_count=0`, a present `source_flows/` directory, and no
`hardware_completion_eligible=true` or `deliverable_complete=true` claim
upgrade.  It writes the canonical `source_flow_map.json`,
`source_flow_map_validation.json`, `source_flow_map_status.json`, and
`discovery_status.json`.  `discovery_status.included_run_count` is the ready
all-eight candidate-root count; `source_flow_mapped_count` and
`source_flow_missing_count` still come from binding those roots against the
packet index.  Any mapped count below 288 or missing count above zero remains a
partial/blocked release map and cannot be reported as full 36×8 closure.
Auto-discovery does not run tools, parse hard-gate verdicts, certify PPA,
select trusted winners, or upgrade hardware/full-SCF/deliverable completion.

When a human or team lane needs the next EDA batch, use the non-executing queue
planner rather than hand-editing launch commands:

```bash
python3 dse_v2/scripts/dse/plan_dft_hardware_closure_next_source_flow_batch.py \
  --out runs/dse/<next_source_flow_batch_plan>/next_source_flow_batch.json \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --run-root runs/dse \
  --max-new-candidates 2 \
  --emit-shell
```

The planner emits recommendations only.  It excludes ready all-eight candidates
and obvious in-flight runs, uses exact candidate matching, and refuses to emit
runnable commands when the packet index is invalid.  The optional shell file is
a review artifact, not an automatically executed EDA job, and it carries no
hardware or deliverable completion claim.

Before scaling materialization across the 36-candidate × 8-kernel matrix,
generate a source-flow plan:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_source_flow_plan.py \
  --out runs/dse/<source_flow_plan_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --source-flow-map runs/dse/<source_flow_map_run>/source_flow_map.json
```

The source-flow-plan helper writes
`dft_hardware_closure_source_flow_plan.json`,
`dft_hardware_closure_source_flow_plan_validation.json`, and
`dft_hardware_closure_source_flow_plan_status.json`.  It enumerates every
packetized candidate/kernel unit (36 × 8 = 288 units for the current release
target), binds each unit to at most one source-flow directory, records the
source manifest path/hash, and validates candidate/kernel identity before raw
files are copied or wrapped.  It blocks missing source flows, wrong-candidate
reuse, wrong-kernel reuse, reused source-flow directories, missing manifests,
and manifest/path/hash mismatches.  It must keep
`adjudication_result=not_adjudicated_by_source_flow_plan`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.  A valid source-flow plan can make raw-stage
materialization eligible for exact rows only; it cannot pass golden,
simulation, synthesis, Vivado, DC, PPA, Pareto, hardware-completion, or
deliverable-completion gates.

If a real kernel RTL/HLS flow has already produced candidate/kernel outputs,
materialize those outputs into the packet-expected raw filenames before
registration:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_raw_stage_materialization.py \
  --out runs/dse/<closure_run> \
  --closure-packet-index runs/dse/<closure_run>/dft_hardware_closure_packet_index.json \
  --evidence-root runs/dse/<closure_run> \
  --source-flow-dir runs/dse/<kernel_rtl_or_hls_flow> \
  --candidate-id <release_candidate_id> \
  --kernel-id <major_kernel_id>
```

The raw-stage-materialization helper writes
`dft_hardware_closure_raw_stage_materialization.json`,
`dft_hardware_closure_raw_stage_materialization_validation.json`, and
`dft_hardware_closure_raw_stage_materialization_status.json`.  It copies or
wraps **existing** source-flow outputs (for example VCS logs, Vivado synthesis
reports, golden traces) into packet-required raw filenames for the exact
candidate/kernel unit.  It does not run tools, does not register hashes, does
not parse results, and must keep
`adjudication_result=not_adjudicated_by_raw_stage_materialization`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.  Missing DC files remain missing; partial stage
materialization is progress evidence only and cannot close the release.
The materializer now records packet-required raw-stage gaps explicitly through
`missing_required_raw_stage_file_count` and per-unit
`missing_required_raw_stage_files[]`.  The canonical Wave31 ASIC example is
`dc_synth.ddc`: the packet-required file must be a real candidate/kernel-specific
Design Compiler design database emitted by the target-library run.  DC logs,
timing/area reports, QoR summaries, mapped Verilog, and parser-derived
target-library diagnostics may be listed as diagnostic
`source_alternatives_present`, but they are not copied into the `.ddc` slot and
cannot satisfy the DC ASIC gate.

When candidate-specific raw files have been produced by a closure lane, register
their SHA-256 transcript refs before parser execution:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_raw_transcript_registration.py \
  --out runs/dse/<raw_transcript_registration_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --evidence-root runs/dse/<closure_packets_run>
```

The raw-transcript-registration helper writes
`dft_hardware_closure_raw_transcript_registration.json`,
`dft_hardware_closure_raw_transcript_registration_validation.json`, and
`dft_hardware_closure_raw_transcript_registration_status.json`.  It opens the
already-staged per-unit `raw_transcript_index.json`, verifies existing raw files
stay under the evidence root and match the exact candidate/kernel when JSON
metadata is present, then records candidate-specific SHA-256 refs.  It never
creates raw evidence, never parses logs, and never passes hard gates:
`adjudication_result=not_adjudicated_by_raw_transcript_registration`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false` must remain true.  Shared microkernel smoke refs,
absolute paths, parent traversal, hash tampering, and claim-upgrading transcript
payloads remain blockers.

After a closure lane starts writing candidate-specific raw evidence files, run
the file-presence intake before any hard-gate adjudication:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_evidence_intake.py \
  --out runs/dse/<closure_intake_run> \
  --closure-packet-index runs/dse/<closure_packets_run>/dft_hardware_closure_packet_index.json \
  --evidence-root runs/dse/<closure_packets_run>
```

The intake helper writes `dft_hardware_closure_evidence_intake.json`,
`dft_hardware_closure_evidence_intake_validation.json`, and
`dft_hardware_closure_evidence_intake_status.json`.  It checks whether each
packet's candidate bundle and expected evidence filenames exist and records
hashes for present files.  Intake rejects candidate-bundle and expected-evidence
paths that escape the evidence root.  It does **not** parse tool logs, judge
numerical correctness, decide Vivado/DC timing closure, select Pareto winners,
or mark a deliverable complete; its `adjudication_status` must remain
`not_adjudicated_by_intake`.

Run the candidate-specific hard-gate parsers against the intake bundle before
building or refreshing the parsed-evidence manifest:

```bash
python3 dse_v2/scripts/dse/run_dft_hardware_closure_parsers.py \
  --out runs/dse/<closure_parser_run> \
  --closure-evidence-intake runs/dse/<closure_intake_run>/dft_hardware_closure_evidence_intake.json \
  --evidence-root runs/dse/<closure_packets_run> \
  --parsed-root runs/dse/<closure_parser_run>
```

The parser-run helper writes `dft_hardware_closure_parser_run.json`,
`dft_hardware_closure_parser_run_validation.json`,
`dft_hardware_closure_parser_run_status.json`, and, only when the exact
candidate bundle, all required unit-level provenance files
(`tool_versions.json`, `command_manifest.json`, `raw_transcript_index.json`,
and `source_bundle_manifest.json`), and all required raw files for a
candidate/kernel/stage are already present, parsed stage-result JSON files under
`parsed_hard_gate_results/<candidate>/<kernel>/<stage>_parsed_result.json`.
The source-bundle manifest must declare the matching `candidate_id`,
`kernel_id`, `candidate_specific_closure=true`, and a candidate-specific raw
evidence scope; shared microkernel smoke artifacts are blocked from becoming
candidate-specific stage passes.  The raw transcript index must separately
reference every present raw stage file with a candidate-specific SHA-256 ref;
staged empty transcript indexes only unblock provenance checks and still leave
the parser blocked on missing/raw-unreferenced stage evidence.  Missing bundles,
missing provenance, invalid candidate-specific provenance, invalid evidence
paths, missing raw files, or raw files absent from the transcript index become
blocker rows; no parser is allowed to invent raw evidence.  Parser output is
readiness evidence only:
`adjudication_result` remains `not_adjudicated_by_parser_run`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.
Parser rows expose `stage_blocker_ids` and `raw_stage_blocker_details` so a
missing packet file such as `dc_synth.ddc` is reported as
`missing_dc_synth_ddc_design_database`, not a generic parser absence.  If all
DC raw files are present, the parser must still record target-library discovery
status/identity and keep ASIC PPA fail-closed when the logs show placeholder
libraries such as `your_library.db`, target-library loss, gtech-only final
mapping, unmapped logic, unconstrained timing, or non-physical zero cell area.
Those cases produce explicit DC blocker ids and `verdict=blocked`; mapped
Verilog, reports, logs, and `.ddc` presence do not override a blocked DC parser
verdict.

Create the stage-level closure adjudication ledger from the intake bundle:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_adjudication.py \
  --out runs/dse/<closure_adjudication_run> \
  --closure-evidence-intake runs/dse/<closure_intake_run>/dft_hardware_closure_evidence_intake.json
```

The adjudication helper writes `dft_hardware_closure_adjudication.json`,
`dft_hardware_closure_adjudication_validation.json`, and
`dft_hardware_closure_adjudication_status.json`.  It expands each candidate ×
kernel unit into the five hard-gate rows (golden correctness, HLS/RTL
simulation, HLS/RTL synthesis, Vivado FPGA synthesis/implementation, and DC
ASIC synthesis/timing/area).  In the current scaffold all rows keep
`adjudication_result=not_adjudicated`, `passed=false`,
`hardware_completion_eligible=false`, and `deliverable_complete=false` until
later parsers attach candidate-specific parsed results for that exact
candidate/kernel/stage.

Build the parsed-evidence manifest expected by later adjudicators:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_parsed_evidence_manifest.py \
  --out runs/dse/<closure_parsed_manifest_run> \
  --closure-adjudication runs/dse/<closure_adjudication_run>/dft_hardware_closure_adjudication.json \
  --parsed-root runs/dse/<closure_parser_run>
```

The parsed-evidence helper writes
`dft_hardware_closure_parsed_evidence_manifest.json`,
`dft_hardware_closure_parsed_evidence_manifest_validation.json`, and
`dft_hardware_closure_parsed_evidence_manifest_status.json`.  It defines the
minimal parsed stage result schema (`dse.dft.hardware_parsed_stage_result.v1`)
for the five hard gates and records expected/missing/present parser output
files under `parsed_hard_gate_results/<candidate>/<kernel>/<stage>_parsed_result.json`.
Even if a parser output declares `verdict=passed`, the manifest keeps
`passed_stage_count=0` and
`adjudication_result=not_adjudicated_by_parsed_manifest`; a separate hard-gate
adjudicator must still decide whether that parser output satisfies the stage.
Refresh this manifest after parser runs; building it before parser output exists
is allowed for a fail-closed readiness view, but gate adjudication will then see
the corresponding stage rows as missing/blocked.

Run the hard-gate adjudicator after the parsed-evidence manifest:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_gate_adjudication.py \
  --out runs/dse/<closure_gate_adjudication_run> \
  --parsed-evidence-manifest runs/dse/<closure_parsed_manifest_run>/dft_hardware_closure_parsed_evidence_manifest.json
```

The gate-adjudication helper writes
`dft_hardware_closure_gate_adjudication.json`,
`dft_hardware_closure_gate_adjudication_validation.json`, and
`dft_hardware_closure_gate_adjudication_status.json`.  It may record
`stage_gate_passed=true` for a valid parsed `verdict=passed` row for the exact
candidate/kernel/stage, but it keeps `hardware_completion_eligible=false` and
`deliverable_complete=false`.  Even if all five stage gates pass for one
candidate × kernel unit, the status remains pending release-level claim closure;
full DFT deliverable completion still requires every claimed kernel and
candidate to close the required gates and the later release claim gate to pass.

Roll the per-unit hard-gate adjudication up to release scope:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_closure_release_gate.py \
  --out runs/dse/<closure_release_gate_run> \
  --gate-adjudication runs/dse/<closure_gate_adjudication_run>/dft_hardware_closure_gate_adjudication.json
```

The current aggregate Step5 runner intent is to collect independently produced
Wave33/36×8 lane outputs into the normal Step5 report/audit surface, not to
replace any closure helper or weaken the gates.  It should ingest the same
workplan, shard, packet, source-flow plan, raw-stage materialization,
raw-transcript registration, parser, gate-adjudication, and release-gate
artifacts and summarize counts of
passed, blocked, failed, missing, and not-adjudicated candidate/kernel units.
The aggregate runner must keep `deliverable_complete=false` while any required
36×8 unit remains unproven, even when a smaller candidate-scoped release gate
passes.

Wave34 adds the required source-flow-plan layer to this aggregate sequence.
The runner now emits `dft_hardware_closure_source_flow_plan` before raw-stage
materialization and materializes only rows whose source-flow manifest proves
the exact candidate/kernel binding.  This prevents copying one candidate's
eight smoke/microkernel flow directories into the other 35 release candidates
as fake closure; unmatched or mismatched source-flow map entries become
visible blockers rather than hidden partial progress.

Current Wave34 probe status:
`runs/dse/ralph_wave34_source_flow_plan_probe_expected_files_20260520T023516Z` enumerates the
full 288-unit matrix.  The previous Wave33 one-candidate source map has 8
source-flow directories and 280 missing rows, but those 8 directories are not
materialization-eligible under the stricter source-flow plan because their
manifests do not declare the release `candidate_id`.  This is a blocker, not a
downgrade: future RTL/HLS/Vivado/DC lanes must stamp `--candidate-id` (or
otherwise produce a manifest with the exact release candidate ID) before their
outputs can feed 36×8 materialization.

Wave35 source-flow closure starts from that blocked Wave34 result.  The next
manual contract is to generate or stage a complete 36 × 8 `source_flow_map.json`
with one row per release `candidate_id` and major `kernel_id`, where every row
points to a source-flow directory whose `manifest.json` declares the same
candidate and kernel.  The accepted map shape is the explicit list form:

```json
{
  "flows": [
    {
      "candidate_id": "<release_candidate_id>",
      "kernel_id": "<major_kernel_id>",
      "source_flow_dir": "runs/dse/<candidate_kernel_source_flow_run>"
    }
  ]
}
```

For the current release target this map must contain 288 intended bindings.
Rows may remain blocked while source flows are still missing, but raw-stage
materialization must not run from an unvalidated or candidate-unstamped map.
Run `build_dft_hardware_closure_source_flow_plan.py` first and treat
`dft_hardware_closure_source_flow_plan_validation.json` plus
`dft_hardware_closure_source_flow_plan_status.json` as the materialization
gate.  Only rows in `dft_hardware_closure_source_flow_plan.json` with
`source_flow_present=true` and `materialization_eligible=true` may feed
`dft_hardware_closure_raw_stage_materialization.json` or the aggregate
`run_dft_hardware_closure_step5_sequence.py` path.  A status such as
`blocked_no_valid_source_flows` or `blocked_partial_source_flow_plan` is an
execution blocker for the missing/mismatched rows, not permission to reuse
another candidate's evidence.

Parallel Wave35 lanes must also keep source-flow provenance one-to-one.  Do not
point multiple candidate/kernel rows at the same source-flow directory, copy a
passing `manifest.json` between candidates, restamp source manifests after raw
evidence exists, or let a kernel-specific smoke directory satisfy another
kernel.  The source-flow plan deliberately reports
`blocked_reused_source_flow_count`,
`blocked_wrong_candidate_reuse_count`, `blocked_wrong_kernel_reuse_count`,
`blocked_invalid_manifest_count`, and `provenance_mismatch_count` so these
evidence-reuse attempts remain visible blockers.

Wave35 generated the 36-candidate × 8-kernel set of 288 candidate-stamped local
source-flow directories, but that result is still source-flow presence only.
Those directories do not contain or imply parsed hard-gate success, PPA closure,
release eligibility, or deliverable completion.  Until a row is selected,
validated by `dft_hardware_closure_source_flow_plan.json`, materialized,
registered, parsed, adjudicated, and rolled up through the release gate, it
remains pre-gate provenance.

Wave36 adds the real source-flow runner above.  The first verified one-candidate
run
`runs/dse/wave36_real_source_flow_run_cand_0715923dc14b29cd_all8_20260520T033600Z`
ran candidate `cand_0715923dc14b29cd` across all eight major kernels through
`ssh_target=ic-eda` (`skip_remote=false`) and produced
`source_flow_ready_count=8`, `blocked_unit_count=0`,
`adjudication_result=not_adjudicated_by_real_source_flow_run`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.  The filtered Step5 run
`runs/dse/wave36_step5_real_source_flow_cand_0715923dc14b29cd_all8_20260520T034024Z`
then wrote 40 parsed stage results, passed 40 stage gates, passed 8 unit gates,
and passed 1 candidate gate for that filtered candidate scope, with
`hardware_completion_eligible=true` and `deliverable_complete=false`.

The latest rolling merged Wave36 evidence in this manual revision is
`runs/dse/wave36_latest_source_flow_map_auto_ready_20260520T061756Z` and
`runs/dse/wave36_step5_real_source_flow_all288_20260520T061902Z`:
36 candidates × 8 kernels = 288 units reached the Step5 hardware release-gate
roll-up, with `stage_gate_passed_count=1440`,
`unit_gate_passed_count=288`, `candidate_gate_passed_count=36`,
`source_flow_present_count=288`, and `source_flow_missing_count=0`.
This is **source-flow + hard-gate release eligibility**, not deliverable
completion: `dft_hardware_closure_release_gate.json` sets
`hardware_completion_eligible=true` but keeps `deliverable_complete=false`,
and the goal audit remains `in_progress`/blocked until the DFT evidence
ledger, trial/candidate/workplan provenance, current-goal L4 bridge/crosswalk rows,
full-SCF evaluated-hybrid artifacts, host-inclusive costs, trusted major-kernel
matrix, and release claim gate all close.  Treat this as the current hardware
gate checkpoint; newer status should still be read from the latest
`discovery_status.json`, `source_flow_map_status.json`, Step5 release gate,
and `dft_scf_hardware_goal_completion_audit.json`.

Wave32 status is progress, not deliverable completion: one release candidate has
all eight major-kernel units passed through the candidate/kernel hard-gate path,
but the full 36-candidate × 8-kernel release remains blocked until every
required release candidate and kernel unit has the same candidate-specific
evidence and release-gate pass.  Wave33 should therefore run the 36×8 closure
lanes in parallel and feed their outputs into the aggregate Step5 rollup rather
than extrapolating from the one-candidate Wave32 success.

The release-gate helper writes `dft_hardware_closure_release_gate.json`,
`dft_hardware_closure_release_gate_validation.json`, and
`dft_hardware_closure_release_gate_status.json`.  It may set
`hardware_completion_eligible=true` only when every required candidate × kernel
unit gate has passed with no missing, blocked, failed, or not-adjudicated units.
Any missing raw ASIC `.ddc` evidence or blocked DC target-library discovery keeps
the release blocked.  Partial candidate/kernel closure cannot be rolled up to
release eligibility.  It still keeps `deliverable_complete=false`: final
deliverable completion requires the separate full-system release/goal claim
gate, including full-SCF accounting, trusted reporting, and the active date
horizon.

The trial-ledger helper writes:

- `dft_trial_state_ledger.json`;
- `dft_trial_transition_report.json`;
- `dft_trial_artifact_refs.json`;
- `dft_trial_state_ledger_validation.json`;
- `dft_trial_ledger.sqlite`.

Each trial row carries `campaign_id`, `workload_run_id`, `trial_id`,
`design_point_id`, `candidate_id`, candidate tier/template, legal transition
history, binding refs, evidence refs, blockers, next actions, and fail-closed
`completion_eligible` / `deliverable_complete` flags.  The
`candidate_binding` block records the search ID, bound release ID, binding
confidence, release assignments, evidence-row presence, and the same
non-upgrade claim boundary.  Step5 cites the bundles under
`dft_candidate_binding_map`, `dft_hardware_completion_workplan`,
`dft_hardware_closure_shards`, `dft_hardware_closure_packets`,
`dft_hardware_closure_candidate_bundles`,
`dft_hardware_closure_unit_provenance`,
`dft_hardware_closure_source_flow_plan`,
`dft_hardware_closure_raw_stage_materialization`,
`dft_hardware_closure_raw_transcript_registration`,
`dft_hardware_closure_evidence_intake`,
`dft_hardware_closure_adjudication`,
`dft_hardware_closure_parsed_evidence`,
`dft_hardware_closure_parser_run`,
`dft_hardware_closure_gate_adjudication`,
`dft_hardware_closure_release_gate`, `dft_l4_goal_binding`, and
`dft_trial_state_ledger`; the goal audit checks these sections are present,
validation-passing, and fail-closed.
This is state/audit provenance only: a binding row, work item, shard queue,
closure packet, candidate-bundle template, unit-provenance staging row,
source-flow-plan row,
raw-stage-materialization row, raw-transcript-registration row,
evidence-intake row, adjudication scaffold row,
parsed-evidence manifest row, parser-run row, gate-adjudication row,
release-gate rollup, L4 binding row, or trial transition cannot upgrade
numerical correctness, trusted Pareto, FPGA PPA, ASIC PPA, or deliverable
completion without the independent full-system release claim gate.

`dft_l4_goal_binding.json` records whether L4/gem5 evidence is explicitly
bound to the current goal.  Historical 9 × 4 or 36-row L4 matrices may remain
visible for provenance, but current-goal proof requires explicit 36-candidate ×
6-workload crosswalks plus row-level proof files under the regenerated root.
Build a historical-evidence binding with:

```bash
python3 dse_v2/scripts/dse/build_dft_l4_goal_binding.py \
  --out runs/dse/<step5_run> \
  --l4-root runs/dse/complete_dse_full_l4_evidence_final_20260519T040705Z \
  --step5-run runs/dse/<step5_run> \
  --quiet
```

The older binding can report `l4_software_visible_proof_present=true` for the
cited 36-row historical L4 matrix while keeping `current_goal_l4_bound=false`
when candidate/workload identities are not proven for the current 36-candidate,
six-SCF target.

The current-goal bridge artifact set is built with:

```bash
python3 dse_v2/scripts/dse/build_dft_current_goal_l4_bridge.py \
  --out runs/dse/<step5_run>/current_goal_l4_bridge \
  --release-gate runs/dse/<step5_run>/dft_hardware_closure_release_gate.json \
  --six-scf-manifest runs/dse/<six_scf_probe>/dft_scf_six_class_bundle_manifest.json \
  --allow-blocked \
  --quiet
```

The latest bridge at
`runs/dse/wave36_step5_real_source_flow_all288_20260520T061902Z/current_goal_l4_bridge/`
writes:

- `dft_current_goal_l4_bridge.json` with
  `status=passed_identity_bridge_ready_for_regenerated_l4`,
  `actual_candidate_count=36`, `actual_workload_count=6`,
  `expected_l4_row_count=216`, `qe_reference_evidence_present=false`, and
  `deliverable_complete=false`;
- `current_goal_l4_crosswalk.json` with
  `status=exact_structured_crosswalk_for_regenerated_current_goal_l4_root`,
  `candidate_crosswalk_count=36`, `workload_crosswalk_count=6`, and
  `regenerated_l4_root_expected_row_count=216`.

The regenerated current-goal L4 proof root is
`runs/dse/current_goal_l4_regenerated_36x6_20260520T091000Z`.  Its evidence
report has `expected_row_count=216`, `row_count=216`, and
`real_l4_gem5_full_flow_rows=216`; all 216 row-level `gem5_l4_proof.json`
files are present and pass, and `gem5_preflight.json` has no blockers.  The
rebuilt Step5 binding
`runs/dse/wave36_step5_real_source_flow_all288_20260520T061902Z/dft_l4_goal_binding_status.json`
therefore has `status=passed`,
`binding_status=passed_current_goal_l4_bound`, `current_goal_l4_bound=true`,
and `l4_software_visible_proof_present=true`.

This L4 proof is software-visible transport proof only.  The L4 matrix/report
still has deliverable blockers such as missing QE baseline, missing trusted
correctness, and missing accelerated numerical correctness, so
`deliverable_complete=false` remains correct.  The bridge/proof artifacts do
not fabricate QE, FPGA, ASIC, or PPA evidence.  The
`legacy_9x4_crosswalk_assessment` remains `status=insufficient_for_current_goal`
with blocker `old_9x4_crosswalk_insufficient_for_36x6_current_goal`; the old
9-candidate × 4-workload crosswalk must not be reused as proof for the current
36 × 6 goal.

### Goal-level anti-downgrade audit

The current long-running goal has a date gate of `2026-06-01 12:00:00 CST`.
Use the goal audit script to turn the active Step5 report into a
prompt-to-artifact checklist before any completion claim:

```bash
python3 dse_v2/scripts/dse/audit_dft_scf_hardware_dse_goal_completion.py \
  --run-dir runs/dse/<step5_run> \
  --out runs/dse/<step5_run>/dft_scf_hardware_goal_completion_audit.json \
  --allow-in-progress
```

Before the goal audit can clear the five semantic HIGH findings, build a
source-hash-backed semantic closure artifact:

```bash
python3 dse_v2/scripts/dse/build_dft_audit_semantic_closure.py \
  --run-dir runs/dse/<step5_run> \
  --out runs/dse/<step5_run>/dft_audit_semantic_closure.json
```

`dft_audit_semantic_closure.json` has schema
`dse.dft_scf.semantic_audit_closure.v1` and is required to carry hashed source
refs plus five machine-readable sections:
`phase_hotspot_identity`, `evaluation_policy_legality`,
`candidate_tier_absence`, `coverage_vector_derivation`, and
`reference_hash_admission`.  It is an audit-hardening artifact only: it can
prove the five semantic findings are closed, but it cannot mark hardware release
eligibility, trusted Pareto winners, FPGA/ASIC PPA, or the final DFT/QE
hardware-DSE deliverable complete.

The audit checks the `date` horizon, Step5 report presence, semantic audit
closure presence/source hashes, DFT evidence ledger presence, DFT trial-state
ledger visibility/validation, L4/gem5 binding visibility plus current-goal
bridge/crosswalk rows, `release_claim_gate.deliverable_complete`, full-SCF
hybrid bundle visibility, host-inclusive cost fields, major-kernel matrix trust,
hardware completion eligibility from either the attached DFT ledger or the
current Step5 release gate, and the rule that Step5 must not upgrade a trusted
winner while DFT deliverable completion is false.  Before the date horizon,
while semantic closure is missing/stale/failed, or while any hard-evidence
row/crosswalk is blocked, the audit must return `in_progress`.

### Stale-term migration scan

Before claiming a docs/manual or front-door alignment checkpoint, run:

```bash
python3 dse_v2/scripts/dse/scan_dft_scf_stale_terms.py \
  --out runs/dse/<audit_run>/dft_scf_stale_term_scan.json
```

`must_fix` hits block completion.  The scanner currently fails old date-horizon
labels, stale wording that implies the DFT/QE proof path is removed, and old
midnight completion labels.  It also records allowed migration reminders such as the
legacy `step3_searchable` alias, whose canonical replacements are
`step2_screenable`, `step3_evaluable`, `simulation_eligible`, and
`simulation_blockers`.

## 9. Wave-2 evidence support surfaces

The current Wave-2 support code adds two replayable evidence surfaces:

- `dse_v2.codesign.dft_hardware_evidence.build_major_kernel_evidence_matrix`
  builds a fail-closed eight-kernel disposition/claim matrix.
- `dse_v2.codesign.dft_hardware_evidence.build_ic_eda_tool_availability_report`
  normalizes IC/EDA tool probes.

CLI entry points:

```bash
python3 dse_v2/scripts/dse/probe_dft_ic_eda_tools.py \
  --local-ic-first \
  --ssh-target ic-eda \
  --out runs/dse/<ic_eda_probe_run>

python3 dse_v2/scripts/dse/build_dft_hardware_evidence_matrix.py \
  --kernel-dispositions <kernel_dispositions.json> \
  --evidence-rows <evidence_rows.json> \
  --candidate-id <candidate_id> \
  --out runs/dse/<matrix_run>

python3 dse_v2/scripts/dse/build_dft_candidate_evidence_ledger.py \
  --release-artifact-dir <release_domain_dir> \
  --ic-eda-tool-availability runs/dse/<ic_eda_probe_run>/ic_eda_tool_availability.json \
  --dft-hardware-evidence-matrix runs/dse/<matrix_run>/dft_hardware_evidence_matrix.json \
  --out runs/dse/<ledger_run>
```

First Ralph Wave-2 probe evidence showed the `ssh ic-eda` environment reachable
and `dc_shell`, `vcs`, and `vivado` version commands available.  This is
availability-only evidence.  The next required closure work is per-kernel
golden correctness, HLS C-sim or RTL sim, HLS C-synth or RTL synth, Vivado
synthesis/implementation for FPGA claims, and DC synthesis/timing/area for ASIC
claims.

Wave24 refreshes that bridge with a fresh `probe_dft_ic_eda_tools.py` artifact
and makes the claim boundary explicit in Step5: `ic_eda_tool_availability.json`
may have `status=passed` and record raw local/SSH attempts, including
non-zero-returncode version output such as `dc_shell -version`, but it still
sets `completion_claim=availability_only_not_kernel_ppa`,
`kernel_ppa_evidence=false`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.  Treat this as scheduling evidence for the next
per-candidate Vivado/DC/VCS/HLS runs, not as candidate-specific PPA or closure.
Rows with `command not found`/`not found`/missing-tool text must remain blocked
even if a wrapper returns zero, and row-level `completion_eligible` is false;
the row-level pass bit is `availability_probe_passed`.  Step5 also clamps any
mislabeled availability payload back to availability-only and records
`ic_eda_tool_availability_payload_claim_boundary_valid=false` for the goal
audit to block completion.

Wave35 keeps the same availability-vs-PPA boundary while source-flow closure
scales.  `ic_eda_tool_availability.json` and `ic_eda_tool_attempts.json` may be
attached to plan tool scheduling, but they are not valid `source_flow_map.json`
rows, not candidate/kernel `manifest.json` source-flow evidence, and not PPA.
Each claimed candidate/kernel unit still needs its own golden, VCS/HLS or RTL
simulation, HLS/RTL synthesis, Vivado FPGA, and/or DC ASIC artifacts to pass the
later parser and gate-adjudication stages.

When the probe and matrix are attached to the DFT candidate evidence ledger,
`eda_all_candidate_evidence.json` records their paths/hashes and status fields
(`tool_availability_status`, `major_kernel_matrix_status`,
`major_kernel_matrix_trusted`).  The ledger must still keep
`hardware_completion_eligible=false` and `deliverable_complete=false` until
per-candidate kernel tool artifacts and final PPA/timing/area evidence pass.
Per-candidate EDA rows also carry `candidate_hardware_gate_summary`: a matching
matrix can make a candidate's major-kernel gate state auditable
(`kernel_gate_audit_ready=true`), but `hardware_gate_claim_eligible` remains
false for host-bound-only matrices and `completion_eligible` remains false
until all non-EDA hard-evidence classes also close.

The same ledger can attach a full-SCF evaluated-hybrid bundle with
`--full-scf-hybrid-artifact-dir`.  This records descriptor/schedule/residency
paths and hashes in `full_scf_hybrid_bundle` and the prompt checklist, but the
completion claim remains `descriptor_accounting_only_not_full_scf_completion`.
It is an accounting/reporting attachment, not all-candidate numerical,
SystemC/gem5, formal, runtime/compiler, FPGA, or ASIC closure.
Step5 now consumes those ledger refs when the bundle lives outside the Step5
directory, so final reports can stay connected to the hashed descriptor bundle
without copying profile-owned artifacts into the generic report directory.

## 10. Wave-3 DFT RTL smoke flows

`dse_v2/scripts/dse/run_dft_kinetic_add_rtl_flow.py` is the first DFT-scoped
replayable microkernel RTL flow.  It writes a fixed-point `kinetic_add` RTL
kernel/testbench plus Vivado/DC TCL scripts, then can use `ssh ic-eda` to run:

- golden fixed-point correctness;
- VCS RTL simulation;
- Vivado FPGA synthesis/utilization/timing-summary;
- DC attempt for ASIC audit.

Example:

```bash
python3 dse_v2/scripts/dse/run_dft_kinetic_add_rtl_flow.py \
  --out runs/dse/<kinetic_add_rtl_run> \
  --ssh-target ic-eda \
  --timeout-s 900 \
  --allow-blocked
```

`dse_v2/scripts/dse/run_dft_reduction_dot_rtl_flow.py` is the second
DFT-scoped replayable microkernel RTL flow.  It writes a deterministic
fixed-point `reduction_dot_tree` dot-product tree RTL kernel/testbench plus
Vivado/DC TCL scripts, then can use the same `ssh ic-eda` path:

```bash
python3 dse_v2/scripts/dse/run_dft_reduction_dot_rtl_flow.py \
  --out runs/dse/<reduction_dot_rtl_run> \
  --ssh-target ic-eda \
  --timeout-s 900 \
  --allow-blocked
```

`dse_v2/scripts/dse/run_dft_transpose_layout_rtl_flow.py` is the third
DFT-scoped replayable microkernel RTL flow.  It writes a deterministic
fixed-width 2x2 `transpose_layout_conversion` pack/unpack transpose RTL
kernel/testbench plus Vivado/DC TCL scripts, then can use the same `ssh ic-eda`
path:

Wave32 tightened this lane after DC correctly rejected a wire-only transpose as
`dc_area_not_physical`: the reference RTL now includes a clocked
`in_valid/out_valid` pipeline register around the lane permutation.  This keeps
the proof target honest as a staged layout-conversion datapath with real
sequential cells, not a zero-area alias.  A transpose ASIC or FPGA claim still
requires the normal gate sequence and cannot be inferred from source generation
or raw-stage materialization alone.

```bash
python3 dse_v2/scripts/dse/run_dft_transpose_layout_rtl_flow.py \
  --out runs/dse/<transpose_layout_rtl_run> \
  --ssh-target ic-eda \
  --timeout-s 900 \
  --allow-blocked
```

`dse_v2/scripts/dse/run_dft_dma_hbm_rtl_flow.py` is the fourth DFT-scoped
replayable microkernel RTL flow.  It writes a deterministic
`dma_hbm_movement_engine` address-generator RTL kernel/testbench covering burst,
strided, gather, and scatter transfers over a small testbench memory plus
Vivado/DC TCL scripts, then can use the same `ssh ic-eda` path:

```bash
python3 dse_v2/scripts/dse/run_dft_dma_hbm_rtl_flow.py \
  --out runs/dse/<dma_hbm_rtl_run> \
  --ssh-target ic-eda \
  --timeout-s 900 \
  --allow-blocked
```

`dse_v2/scripts/dse/run_dft_hpsi_local_rtl_flow.py` is the fifth DFT-scoped
replayable microkernel RTL flow.  It writes a deterministic fixed-point
`hpsi_local_potential` elementwise local-potential multiply RTL kernel/testbench
plus Vivado/DC TCL scripts, then can use the same `ssh ic-eda` path:

```bash
python3 dse_v2/scripts/dse/run_dft_hpsi_local_rtl_flow.py \
  --out runs/dse/<hpsi_local_rtl_run> \
  --ssh-target ic-eda \
  --timeout-s 900 \
  --allow-blocked
```

`dse_v2/scripts/dse/run_dft_complex_gemm_gemv_rtl_flow.py` is the sixth
DFT-scoped replayable microkernel RTL flow.  It writes a deterministic fixed
2x2 complex `complex_gemm_gemv_tile` RTL kernel/testbench plus Vivado/DC TCL
scripts, then can use the same `ssh ic-eda` path:

```bash
python3 dse_v2/scripts/dse/run_dft_complex_gemm_gemv_rtl_flow.py \
  --out runs/dse/<complex_gemm_gemv_rtl_run> \
  --ssh-target ic-eda \
  --timeout-s 900 \
  --allow-blocked
```

`dse_v2/scripts/dse/run_dft_nonlocal_projector_rtl_flow.py` is the seventh
DFT-scoped replayable microkernel RTL flow.  It writes a deterministic
four-lane fixed-point `nonlocal_projector` RTL kernel/testbench for
`coeff=sum(beta_i*psi_i)` and `out_i=beta_i*coeff` plus Vivado/DC TCL scripts,
then can use the same `ssh ic-eda` path:

```bash
python3 dse_v2/scripts/dse/run_dft_nonlocal_projector_rtl_flow.py \
  --out runs/dse/<nonlocal_projector_rtl_run> \
  --ssh-target ic-eda \
  --timeout-s 900 \
  --allow-blocked
```

`dse_v2/scripts/dse/run_dft_fft_ifft_rtl_flow.py` is the eighth
DFT-scoped replayable microkernel RTL flow.  It writes a deterministic
fixed-width 4-point `fft_ifft_ffft` RTL kernel/testbench covering forward
complex FFT, normalized complex iFFT, and real-input fFFT smoke semantics plus
Vivado/DC TCL scripts, then can use the same `ssh ic-eda` path:

```bash
python3 dse_v2/scripts/dse/run_dft_fft_ifft_rtl_flow.py \
  --out runs/dse/<fft_ifft_rtl_run> \
  --ssh-target ic-eda \
  --timeout-s 900 \
  --allow-blocked
```

These flows intentionally keep DC attempt rows separate from the FPGA claim
matrix.  A Vivado/VCS-backed microkernel matrix can pass only for its matching
`kernel_id`; `kinetic_add`, `reduction_dot_tree`,
`transpose_layout_conversion`, `dma_hbm_movement_engine`,
`hpsi_local_potential`, `complex_gemm_gemv_tile`, `nonlocal_projector`, and
`fft_ifft_ffft` evidence cannot satisfy each other or any other major kernel.
The FFT/iFFT/fFFT lane proves only deterministic 4-point fixed-width complex
FFT, normalized iFFT, and real fFFT smoke semantics, not production FFT size
coverage, full spectral-transform closure, or end-to-end SCF closure.  The
DMA/HBM lane proves only address-generation and small-memory movement semantics
for its microkernel, not full HBM bandwidth, board-level DMA, or end-to-end SCF
movement closure.  The Hψ local-potential and complex-GEMM/GEMV
lanes prove only their fixed smoke arithmetic, not full Hamiltonian or
projector-list coverage.  The nonlocal-projector lane proves only the four-lane
beta-projection/apply smoke semantics, not full projector-list coverage,
pseudopotential integration, or full-SCF nonlocal potential closure.
A DC run without a real ASIC target library remains `blocked` and must not be
reported as ASIC timing/area/PPA.  These are progress evidence lanes for
individual major kernels only; they do not satisfy full-SCF completion, all
major-kernel closure, or all-candidate DSE closure.
