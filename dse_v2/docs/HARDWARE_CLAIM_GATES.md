# Hardware Claim Gates

`dse_v2.codesign.hardware_claim_gates` validates Step3/Step4 evidence records
before any accelerated-kernel FPGA or ASIC claim is allowed.

## Required chain

Every hardware claim must pass:

1. golden/kernel/numerical correctness;
2. HLS C-simulation or RTL simulation;
3. HLS C-synthesis or RTL synthesis;
4. the claim-specific physical branch:
   - FPGA: Vivado synthesis **and** implementation-route completion.  A
     `synth_design` pass, utilization report, or timing summary without an
     explicit `implementation_route_completed=true` payload or
     `ROUTE_DESIGN COMPLETE` log marker is synth-only progress evidence and
     must block the FPGA claim gate with
     `vivado_implementation_route_not_completed`;
   - ASIC: Design Compiler synthesis, timing, area, and the packet-required
     `dc_synth.ddc` design database from a real target-library run.  A combined
     `dc_synth_timing_area` artifact is insufficient without the `.ddc` and
     physical target-library evidence.

DC-only evidence is a blocker for FPGA claims. Vivado-only evidence is a
blocker for ASIC claims. Tool-unavailable logs with command, environment, and
failure evidence are useful audit records, but they remain blockers and never
become pass evidence.

For ASIC claims, `dc_synth.ddc` is mandatory pass evidence alongside the DC
timing/area/log artifacts and real target-library discovery.  DC logs, timing
reports, area reports, QoR summaries, or mapped Verilog without the `.ddc` are
diagnostic blockers only.  They may be archived and parsed to explain a failure,
but they must not satisfy `dc_synth`, `dc_timing`, `dc_area`, ASIC PPA, release,
or deliverable gates.

## Kernel ownership

Evidence is kernel-scoped.  When `kernel_id` is supplied to
`validate_hardware_claim_evidence(...)`, records tagged with another kernel are
ignored and reported as `ignored_kernel_evidence` with the reason
`cross_kernel_evidence_ignored`.  This prevents, for example, a passing FFT
Vivado transcript from satisfying a nonlocal-projector claim.

Rows without a `kernel_id` remain accepted for legacy/common artifacts only
when the caller deliberately passes them into the kernel gate.  DFT/QE major
kernel flows should prefer explicit `kernel_id` on every correctness,
simulation, synthesis, Vivado, and DC row.

## DFT/QE major-kernel matrix

`dse_v2.codesign.dft_hardware_evidence` adds the DFT-profile wrapper that checks
the eight major SCF kernels:

- `fft_ifft_ffft`;
- `transpose_layout_conversion`;
- `hpsi_local_potential`;
- `kinetic_add`;
- `nonlocal_projector`;
- `complex_gemm_gemv_tile`;
- `reduction_dot_tree`;
- `dma_hbm_movement_engine`.

Each row must be one of:

- `accelerated_claim`: runs this claim gate for the row's `claim_type`
  (`fpga`, `asic`, or `fpga_asic`);
- `host_bound`: allowed only when `host_cost_accounted` is true and never as
  acceleration evidence;
- an explicit blocker, which keeps the matrix blocked.

The CLI emits `dft_hardware_evidence_matrix.json`:

```bash
python3 dse_v2/scripts/dse/build_dft_hardware_evidence_matrix.py \
  --kernel-dispositions <kernel_dispositions.json> \
  --evidence-rows <evidence_rows.json> \
  --candidate-id <candidate_id> \
  --out <out_dir>
```

The matrix is a coverage and claim-gate artifact.  It is not full-SCF closure by
itself and cannot promote a candidate if any claimed kernel is missing golden,
simulation, synthesis, or claim-specific physical-tool evidence.

The DFT candidate evidence ledger can attach this matrix with
`--dft-hardware-evidence-matrix`; the ledger records path/hash/status for audit
continuity but must keep EDA completion blocked until per-candidate kernel tool
artifacts pass.
For matching candidate IDs, each EDA candidate row includes
`candidate_hardware_gate_summary` with the matrix status, trusted flag,
host-bound kernels, blocked kernels, and accelerated kernels whose gate passed.
This improves candidate-level auditability but is intentionally not a release
completion gate by itself.

For the current Wave-3 smoke paths, the DFT-scoped RTL microkernel runners are:

- `run_dft_fft_ifft_rtl_flow.py` for `kernel_id=fft_ifft_ffft`;
- `run_dft_hpsi_local_rtl_flow.py` for
  `kernel_id=hpsi_local_potential`;
- `run_dft_kinetic_add_rtl_flow.py` for `kernel_id=kinetic_add`;
- `run_dft_complex_gemm_gemv_rtl_flow.py` for
  `kernel_id=complex_gemm_gemv_tile`;
- `run_dft_reduction_dot_rtl_flow.py` for `kernel_id=reduction_dot_tree`;
- `run_dft_transpose_layout_rtl_flow.py` for
  `kernel_id=transpose_layout_conversion`;
- `run_dft_dma_hbm_rtl_flow.py` for
  `kernel_id=dma_hbm_movement_engine`;
- `run_dft_nonlocal_projector_rtl_flow.py` for
  `kernel_id=nonlocal_projector`.

The transpose/layout lane must remain a real staged datapath.  A wire-only
permutation that DC reports with `Total cell area: 0.000000` is blocked as
`dc_area_not_physical`; the reference lane therefore registers the transposed
lanes behind `clk/rst_n/in_valid/out_valid` before it can contribute ASIC PPA
evidence.  This does not relax the gate sequence: raw sources, raw-stage
materialization, or mapped assign-only Verilog are not substitutes for parsed
Vivado/DC hard-gate evidence.

The current Step2 search artifact writer also emits
`hierarchical_funnel_search_report.json`, which records release-template
coverage and exploratory isolation before physical evidence is attempted.  This
search report is useful for ordering tool runs, but it is not hardware claim
evidence and cannot satisfy any stage in the gate above.

Current Wave32/Wave33 status must be stated with the same fail-closed language:
Wave32 has one release candidate with all eight major-kernel gates passed, but
the full 36-candidate × 8-kernel release remains blocked.  Wave33 parallel lanes
should close the remaining exact candidate/kernel units and let the aggregate
Step5 rollup report counts and blockers; aggregate reporting does not relax the
per-unit gate or the ASIC `dc_synth.ddc`/real-target-library requirement.

Each runner generates only its own kernel RTL, VCS testbench, Vivado
synthesis/implementation TCL, DC TCL, evidence rows, and major-kernel matrix.
Passing rows may satisfy only the matching microkernel gate when
golden/VCS/Vivado evidence passes.  For the FPGA physical branch, Vivado
`synth_design` alone is not a gate pass; the parser must also observe
implementation-route completion as described in the required chain above.  The
FFT/iFFT/fFFT lane covers deterministic 4-point fixed-width complex FFT,
normalized iFFT, and real fFFT smoke semantics only; it does not satisfy Hψ,
reduction, kinetic, projector, GEMM/GEMV, transpose, DMA/HBM, production FFT, or
full-SCF claims.  The DMA/HBM lane covers deterministic burst, stride, gather,
and scatter address generation over a small testbench memory only; it does not
satisfy FFT, Hψ, reduction, kinetic, projector, GEMM/GEMV, transpose, or
full-SCF claims.  The Hψ local-potential lane covers deterministic fixed-point
elementwise local-potential multiply only; it does not satisfy FFT, reduction,
kinetic, projector, GEMM/GEMV, transpose, DMA/HBM, or full-SCF claims.  The
complex GEMM/GEMV lane covers deterministic fixed 2x2 complex matrix-vector
tile arithmetic only; it does not satisfy FFT, Hψ, reduction, kinetic,
projector, transpose, DMA/HBM, or full-SCF claims.  The nonlocal-projector lane
covers only the four-lane beta projection
`coeff=sum(beta_i*psi_i)` plus `out_i=beta_i*coeff` smoke semantics; it does not
satisfy FFT, Hψ, reduction, kinetic, GEMM/GEMV, transpose, DMA/HBM, or full-SCF
claims.  DC rows are stored as separate ASIC-attempt evidence unless they map
against a real target library and produce claimable timing/area/PPA.

The kinetic-add lane also has a direct regression file,
`dse_v2/tests/test_dft_kinetic_add_rtl_flow.py`, so all eight major-kernel
runner families now have named smoke-flow coverage rather than relying only on
shared workstream tests.

## IC/EDA availability probe

`dse_v2/scripts/dse/probe_dft_ic_eda_tools.py` records whether the real IC/EDA
tools are reachable through the configured local/SSH environment:

```bash
python3 dse_v2/scripts/dse/probe_dft_ic_eda_tools.py \
  --local-ic-first \
  --ssh-target ic-eda \
  --out runs/dse/<probe_run>
```

The probe writes:

- `ic_eda_tool_availability.json`;
- `ic_eda_tool_attempts.json`.

Availability is only tool reachability.  It is not kernel PPA, timing, area,
Vivado implementation, Design Compiler synthesis, or SCF-level completion
evidence.  A passing availability artifact is useful for planning the next
tool runs; the per-kernel artifacts still have to be generated and attached to
the hardware claim matrix.

The availability report is intentionally self-labeling:

- `completion_claim = availability_only_not_kernel_ppa`;
- `kernel_ppa_evidence = false`;
- `hardware_completion_eligible = false`;
- `deliverable_complete = false`;
- each tool row records the `availability_evidence_kind`, so a version banner
  observed with a non-zero return code is transparent reachability evidence,
  not a hidden synthesis pass.
- each tool row keeps `completion_eligible = false`; use
  `availability_probe_passed` for reachability, not claim eligibility.
- `command not found`, `not found`, or missing-tool text blocks availability
  even when a shell wrapper returns zero.

Step5 normalizes this payload fail-closed.  If an attached availability JSON is
mislabeled as PPA/completion evidence, Step5 reports the raw label separately,
sets normalized PPA/completion fields to `false`, and marks
`ic_eda_tool_availability_payload_claim_boundary_valid=false` for the goal
audit.

The DFT candidate evidence ledger can attach this probe with
`--ic-eda-tool-availability`.  Attachment means the ledger can cite the probe's
path/hash; it does not change `hardware_completion_eligible=false` by itself.

## Candidate bundle templates are not closure evidence

`dft_hardware_closure_candidate_bundle_index.json` and the referenced
`candidate_bundle.json` files are execution metadata only.  They may describe a
candidate/kernel, stage IDs, command-template IDs, and expected raw evidence
filenames, but they must not contain raw VCS/HLS/Vivado/DC results and must
keep all completion flags false.  Validation recomputes bundle hashes, opens
the actual bundle payloads, rejects any `raw_evidence_file_count > 0`, rejects
`raw_evidence_present=true`, rejects expected evidence rows that mark files
present, and rejects absolute or parent-traversal bundle paths.  A valid bundle
template can make evidence intake count `candidate_bundle_count`, but it cannot
pass golden correctness, simulation, synthesis, FPGA, ASIC, PPA, Pareto, or
deliverable gates.

## Unit provenance staging is not closure evidence

`dft_hardware_closure_unit_provenance_index.json` and the per-unit
`tool_versions.json`, `command_manifest.json`, `raw_transcript_index.json`, and
`source_bundle_manifest.json` files are metadata-only staging artifacts.  At
this stage `raw_transcript_index.json` is an empty/staged transcript index with
`raw_stage_evidence_file_count=0`; it is **not** a raw transcript and does not
contain VCS/HLS/Vivado/DC logs, parsed results, timing, area, or PPA data.

Validation must reject raw stage evidence embedded in the provenance index,
claim-upgrading flags, path escape/hash mismatch, and provenance payloads that
do not match the exact candidate/kernel or candidate-specific closure scope.  A
valid unit-provenance stage can unblock parser provenance checks, but cannot
satisfy golden correctness, simulation, synthesis, Vivado FPGA, DC ASIC, PPA,
Pareto, hardware-completion, or deliverable gates.

## Source-flow planning is not closure evidence

`dft_hardware_closure_source_flow_plan.json` authorizes which existing
source-flow directory may feed which exact candidate/kernel unit before any raw
files are copied or wrapped.  The plan must enumerate the full packetized
matrix (36 release candidates × 8 major kernels = 288 units for the current
target), record source-flow directory refs, record `manifest.json` hashes, and
validate candidate/kernel manifest identity.

Validation must reject or block shared smoke scope, missing source-flow
directories, missing manifests, wrong-candidate reuse, wrong-kernel reuse,
path/hash mismatch, source-flow directory reuse across multiple units, and
evidence copied from another release candidate.  A valid plan can make a row
eligible for raw-stage materialization only; it cannot satisfy golden
correctness, simulation, synthesis, Vivado FPGA implementation, DC ASIC
synthesis/timing/area, PPA, Pareto ranking, hardware-completion, or
deliverable-completion gates.

The plan must keep `adjudication_result=not_adjudicated_by_source_flow_plan`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.  Step5 reports source-flow present, missing,
wrong-candidate, wrong-kernel, reused-source, and provenance-mismatch counts
before raw-stage materialization so aggregate progress cannot silently copy one
candidate's eight smoke flows into other release candidates.

The DFT RTL/HLS smoke runners therefore accept `--candidate-id` and stamp that
release ID into `manifest.json`.  A flow directory whose manifest declares only
`kernel_id` is useful diagnostic history, but it is blocked as
`source_flow_candidate_id_missing` by the source-flow plan and cannot feed
candidate-specific materialization.

For Wave35 source-flow-map closure, the 36 release candidates × 8 major kernels
matrix must be represented as `source_flow_map.json` with explicit `flows[]`
rows:

- `candidate_id`;
- `kernel_id`;
- `source_flow_dir`.

Each `source_flow_dir` must contain the candidate-id-stamped `manifest.json`
for that exact row before it can become materialization eligible.  The
validated handoff is `dft_hardware_closure_source_flow_plan.json` plus
`dft_hardware_closure_source_flow_plan_validation.json` and
`dft_hardware_closure_source_flow_plan_status.json`; raw materialization may
consume only rows where `source_flow_present=true` and
`materialization_eligible=true`.  Source-flow-map generation, source manifests,
and source-flow planning are still pre-gate provenance and must keep
`adjudication_result=not_adjudicated_by_source_flow_plan`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.

Evidence reuse remains fail-closed.  Multiple rows must not share one
`source_flow_dir`, one candidate's `manifest.json`, one kernel's smoke flow, or
one IC/EDA availability probe as a substitute for candidate/kernel evidence.
The expected blocker counters are
`blocked_reused_source_flow_count`,
`blocked_wrong_candidate_reuse_count`, `blocked_wrong_kernel_reuse_count`,
`blocked_invalid_manifest_count`, and `provenance_mismatch_count`; a legacy
manifest without the release candidate remains
`source_flow_candidate_id_missing`.

## Real source-flow execution is not gate adjudication

`dft_hardware_closure_real_source_flow_run.json` records selected
candidate/kernel RTL/HLS source-flow executions.  The runner selects units from
`dft_hardware_closure_packet_index.json`, calls the matching per-kernel RTL flow
script with `--candidate-id`, uses `ssh_target=ic-eda` by default unless
`--skip-remote` is set, passes a candidate/run/kernel-scoped `--remote-dir` to
avoid remote scratch-directory collisions, and emits a candidate/kernel
`source_flow_map.json` plus
`source_flows/<candidate>/<kernel>/...` directories.

This artifact is still pre-gate execution/provenance.  Validation must reject
any claim upgrade and the payload must keep:

- `adjudication_result = not_adjudicated_by_real_source_flow_run`;
- `passed_stage_count = 0`;
- `hardware_completion_eligible = false`;
- `deliverable_complete = false`.

A ready row may become an input to source-flow planning.  It cannot by itself
satisfy golden correctness, HLS/RTL simulation, HLS/RTL synthesis, Vivado FPGA
implementation, DC ASIC synthesis/timing/area, PPA, Pareto ranking,
hardware-completion, or deliverable-completion gates.

Wave35's 288 candidate-stamped local source-flow directories therefore remain
source-flow presence only.  Wave36 provides stronger execution provenance for
selected units, but the same non-upgrade rule applies.  The verified run
`runs/dse/wave36_real_source_flow_run_cand_0715923dc14b29cd_all8_20260520T033600Z`
has `source_flow_ready_count=8`, `blocked_unit_count=0`,
`adjudication_result=not_adjudicated_by_real_source_flow_run`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.  Its filtered Step5 follow-up
`runs/dse/wave36_step5_real_source_flow_cand_0715923dc14b29cd_all8_20260520T034024Z`
passed 40 stage gates, 8 unit gates, and 1 candidate gate for
`cand_0715923dc14b29cd`; that candidate-scoped
`hardware_completion_eligible=true` result is a historical one-candidate
checkpoint, not full 36×8 release completion.

## Latest source-flow map discovery is not claim evidence

`build_dft_hardware_closure_latest_source_flow_map.py` scans completed
`wave36_real_source_flow_run_*_all8_*` manifests and assembles a canonical
`source_flow_map.json` from ready roots.  It includes only runs with
`status=source_flows_ready_pending_step5`, `source_flow_ready_count=8`,
`blocked_unit_count=0`, a present `source_flows/` directory, and no
claim-upgrading `hardware_completion_eligible` or `deliverable_complete` flag.
It also writes `discovery_status.json` with included/excluded run provenance and
blocker IDs.

This latest-map artifact is scheduling/provenance evidence only.  It does not
run EDA tools, parse golden/simulation/synthesis/Vivado/DC verdicts, certify
PPA, or make a full-SCF claim.  `discovery_status.json` and the generated map
must keep `hardware_completion_eligible=false`, `deliverable_complete=false`,
and an explicit `claim_boundary`.  Even when map validation passes, a partial
map with `source_flow_missing_count > 0` is still blocked for those missing
candidate×kernel rows and cannot satisfy release, Pareto, full-SCF, FPGA, ASIC,
or deliverable gates.

The current checkpoint
`runs/dse/wave36_latest_source_flow_map_auto_ready_20260520T061756Z` maps all
288 intended units (36 release candidates × 8 major kernels), while
`runs/dse/wave36_step5_real_source_flow_all288_20260520T061902Z` has been
refreshed under the route-required Vivado parser.  The current roll-up has 1152
passed stage gates and 288 blocked Vivado FPGA stages, all blocked by
`vivado_implementation_route_not_completed`; it has 0 passed unit gates, 0
passed candidate gates, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.  Older synth-only checkpoints that reported
candidate-scoped or release-scoped `hardware_completion_eligible=true` are
historical progress artifacts only and must not be cited as FPGA release
closure until real Vivado implementation-route evidence is present.

## L4/gem5 binding is not FPGA/ASIC PPA or implicit candidate equivalence

`dft_l4_goal_binding.json` cites a complete-DSE gem5/GenericAccel L4 evidence
matrix from a DFT Step5 run.  The binding separates two claims:

- `l4_software_visible_proof_present=true`: the cited matrix is complete for
  its own candidate/workload scope and row-level `gem5_l4_proof.json` files are
  present.
- `current_goal_l4_bound=true`: explicit crosswalks prove that the current DFT
  hardware-closure candidates and workloads are the same identities as the L4
  matrix rows.

The first claim is software-visible model evidence only.  It cannot satisfy
Vivado implementation, DC timing/area, per-kernel hardware gates, six-SCF
workload closure, or final deliverable completion.  If the L4 matrix uses
`cdse_*` candidates or legacy QE mainflows while the hardware closure uses
`cand_*` release candidates and strict full-SCF classes, the binding must keep
`current_goal_l4_bound=false` and list the missing candidate/workload crosswalks
as blockers.

## Raw-stage materialization is not adjudication

`dft_hardware_closure_raw_stage_materialization.json` records that an existing
kernel-flow directory was copied or wrapped into the packet-expected raw
filenames for an exact candidate/kernel unit.  It may place VCS logs, Vivado
reports, golden traces, or DC attempt logs under
`candidate_specific_evidence/<candidate>/<kernel>/`, but it does not run those
tools and cannot by itself register transcript hashes, parse pass/fail results,
or pass hard gates.

The materializer must keep
`adjudication_result=not_adjudicated_by_raw_stage_materialization`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.  Partial materialization is allowed as progress
evidence: if any required file for a stage is still missing, parser and gate
adjudication must keep that stage blocked.

Missing required raw-stage files must be named, not hidden behind a generic
partial-progress label.  For DC ASIC closure, the packet contract requires a
real `dc_synth.ddc`; `dc_shell.log`, `dc_timing.rpt`, `dc_area.rpt`, QoR
summaries, and mapped Verilog are useful diagnostics but are not substitutes.
The canonical blocker id for this gap is
`missing_dc_synth_ddc_design_database`.

When `dc_synth.ddc` is present, the parser still has to confirm real target
library discovery and non-placeholder physical mapping.  Missing or placeholder
target libraries, gtech-only final mapping, unmapped logic, unconstrained timing,
and zero physical cell area produce distinct DC blocker ids rather than a generic
parser failure.  Normal Design Compiler HDL elaboration messages that mention
`gtech` do not block a run when the final reports identify a real target library
and non-zero cell area.

## Raw-transcript registration indexes existing raw files only

`dft_hardware_closure_raw_transcript_registration.json` records SHA-256 refs for
candidate-specific raw stage files that already exist under the evidence root.
It writes refs into the staged per-unit `raw_transcript_index.json` only after
the raw file path is contained under the evidence root and any JSON metadata
matches the exact candidate/kernel.  It rejects shared microkernel smoke scope,
path escape, transcript hash tampering, and claim-upgrading transcript payloads.

Registration is not evidence generation and not adjudication.  It must keep
`adjudication_result=not_adjudicated_by_raw_transcript_registration`,
`passed_stage_count=0`, `hardware_completion_eligible=false`, and
`deliverable_complete=false`.  A registered raw ref may unblock parser reads,
but golden/sim/synth/Vivado/DC hard-gate passes require parser output plus the
separate gate-adjudication and release-gate stages.

Parser runs add another anti-downgrade guard: a stage parser may write a parsed
result only when the candidate bundle exists, the stage raw files exist, the
raw transcript index contains SHA-256 refs for those files, and unit-level
provenance files exist.  In particular, `source_bundle_manifest.json` must
match the exact candidate/kernel and declare candidate-specific closure; shared
microkernel smoke manifests remain blockers even if their logs contain `PASS`.

## Targeted checks

```bash
python3 -m pytest -q dse_v2/tests/test_hardware_claim_gates.py
python3 -m pytest -q dse_v2/tests/test_dft_scf_hardware_dse_workstreams.py
python3 -m pytest -q dse_v2/tests/test_dft_hardware_closure_candidate_bundles.py
python3 -m pytest -q dse_v2/tests/test_dft_hardware_closure_unit_provenance.py
python3 -m pytest -q dse_v2/tests/test_dft_hardware_closure_source_flow_plan.py
python3 -m pytest -q dse_v2/tests/test_dft_hardware_closure_real_source_flow_run.py
python3 -m pytest -q dse_v2/tests/test_dft_hardware_closure_raw_stage_materialization.py
python3 -m pytest -q dse_v2/tests/test_dft_hardware_closure_raw_transcript_registration.py
python3 -m pytest -q dse_v2/tests/test_dft_hardware_closure_parser_run.py
python3 -m pytest -q dse_v2/tests/test_dft_kinetic_add_rtl_flow.py
python3 -m compileall dse_v2
```

This gate does not run DC, VCS, or Vivado itself and does not make timing, area,
PPA, FPGA, or ASIC implementation claims. Real tool transcripts must be
produced by the EDA flow before this validator can allow a matching claim.
