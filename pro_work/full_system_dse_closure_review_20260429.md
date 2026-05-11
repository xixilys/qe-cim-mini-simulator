# Full-system DSE closure review: Baseline QE/F2 and real gem5/B4 gates

Date: 2026-04-29  
Scope: review and documentation pass for the pro_work full-system DSE loop. This
memo covers the frontend Baseline QE/F2 path, the backend SystemC/gem5 path, and
the release/feedback claim ceiling boundary. It is a review artifact, not a new
execution result.

## 1. Non-negotiable acceptance boundary

Baseline QE/F2 and real gem5/B4 are two independent acceptance gates:

| Gate | What it can prove | Required evidence | What it must not claim |
|---|---|---|---|
| Baseline QE/F2 gate | Stage-A/B0 candidate identity, F2 eligibility, SystemC B2 timed-functional/proxy feedback shape, feedback ingest, and release/adjudicator claim ceilings. | `candidate_descriptor_v0`, `backend_execution_request_v0`, metric-bearing `systemc_timed_functional` or explicit not-executed descriptor artifacts, claim-safe feedback adapter tests. | QE numerical equivalence, real gem5 execution, cycle accuracy, RTL/HLS/board/ASIC/physical FPGA performance. |
| Real gem5/B4 gate | Host/runtime/MMIO/DMA/cache/sync proxy observation through gem5 plus an explicit SystemC bridge/target artifact. | `gem5_systemc_timed_proxy` BackendExecutionReport, explicit `systemc_bridge` input ref, B4 control-path metrics, B4 datapath metrics, refusal when bridge evidence is absent. | QE numerical equivalence, board measured speedup, cycle-accurate RTL, production readiness, or automatic promotion from B3 smoke. |

A release bundle may contain both gates, but passing one gate does not imply the
other. Any public recommendation must cite the lowest applicable claim ceiling
for the exact artifact being used.

## 2. Lane review summary

### Lane 1: Baseline B0/B2 contract

Current positive signals:

- `tools/benchmarks/unified_dse/domain_contracts.py` defines domain-neutral IR
  names (`ApplicationGraphIR`, `ArchitectureTemplateIR`, `MappingIR`,
  `EvidenceIR`) and keeps backend reports claim-ceiling validated by fidelity.
- `tools/benchmarks/unified_dse/stage_b0_descriptors.py` emits separate sidecars
  for application graph, architecture template, mapping, candidate descriptor,
  SystemC config, gem5 handoff, and backend execution request.
- Stage-B0 SystemC configs are explicitly `not_executed` and capped at
  `systemc_config_descriptor_only`.

Remaining review risks:

- `systemc_config` is still the executable-facing descriptor while
  `architecture_template` and `mapping` are sidecars. Backend code must not treat
  `architecture_template_ref` as an executable SystemC configuration.
- QE compatibility fields (`qe_anchor_refs`) are still present in Stage-B0
  artifacts for QE rows. That is acceptable for the QE adapter, but generic
  workloads must not inherit QE anchors or QE-equivalence language.
- Baseline B2 promotion needs metric-bearing SystemC reports before it can rank
  beyond descriptor/proxy-contract evidence.

Required documentation wording:

> Stage-B0 artifacts prove descriptor shape and candidate eligibility only. B2
> promotion requires an external or backend-generated metric-bearing
> `systemc_timed_functional` report with an allowed proxy claim ceiling.

### Lane 2: E2E gate, release, and feedback

Current positive signals:

- SystemC feedback validation now requires top-level and row-level claim fields
  (`systemc_feedback_adapter.py`) and rejects row claim ceilings above the
  artifact ceiling.
- Backend release bundle logic preserves backend report ceilings in the manifest
  and claim ceiling matrix.
- Release bundle validation forbids final public family winner claims unless a
  separately authorized artifact introduces that authority.

Remaining review risks:

- Feedback ingest and release packaging should keep a ceiling matrix next to the
  human memo so reviewers can identify exactly which metrics are descriptor,
  proxy, gem5 smoke, B4 timed proxy, correctness-only, or implementation-only.
- Calibration feedback can adjust ranking but is still not a release authority.
  It must remain `calibration_feedback_only` unless tied to a higher-fidelity
  report with its own validated ceiling.

Required documentation wording:

> Feedback updates may change ranking order within their fidelity tier; they do
> not raise the claim ceiling. Release bundles must include a machine-readable
> claim ceiling matrix and must not collapse SystemC, gem5, correctness, and
> implementation evidence into a single performance claim.

### Lane 3: gem5 FPGAAccelerator SimObject/C++ params

Current positive signals:

- The gem5 FPGA device surface exists under `gem5_integration/src/dev/fpga/`,
  with Python SimObject definitions and C++ device implementation files.
- The backend runner passes execution mode and resolved request refs into the
  gem5 environment (`QEBS_EXECUTION_MODE`, `QEBS_GEM5_CONFIG`,
  `QEBS_FPGA_EXECUTION_MODE`, `QEBS_REAL_SYSTEMC_TARGET`).

Remaining review risks:

- SimObject parameters must remain aligned with C++ constructor/field names and
  config scripts. Drift here can make B4 appear configured while the device is
  actually running a default or smoke-only path.
- `smoke`, `timed_proxy`, and `real_bridge` mode selection must be visible in
  config artifacts and reports, not just in comments or environment variables.

Required documentation wording:

> B4 is not accepted unless the gem5 config, SimObject parameters, environment,
> and BackendExecutionReport all agree on `gem5_systemc_timed_proxy` / explicit
> bridge mode. A B3 smoke device configuration is not B4 evidence.

### Lane 4: B4 gem5 runner/config/report

Current positive signals:

- `backend/runners/run_backend_execution_v0.py` maps
  `gem5_systemc_timed_proxy` to B4 and validates `gem5_systemc_timed_proxy_only`.
- B4 runner logic refuses to execute without an explicit `systemc_bridge`,
  `systemc_bridge_library`, `systemc_target`, or `real_systemc_target` input ref.
- B4 direct-report acceptance validates required `control_path` fields and
  required host/SystemC/DMA metrics before accepting a report.

Remaining review risks:

- B4 can still be represented by a refused BackendExecutionReport. That is a
  useful hard gate result, but it is not a B4 pass.
- If an explicit bridge artifact exists but the gem5 config still exercises a
  stub path, the report must say so through `systemc_bridge_status` /
  `real_systemc_target` provenance and remain below any real-bridge claim.

Required documentation wording:

> The real-gem5/B4 gate is hard-fail-by-default. Missing bridge evidence produces
> a refusal report capped at `gem5_systemc_timed_proxy_only`; it does not fall
> back to B3 smoke or local timed-proxy execution.

### Lane 5: SystemC bridge, provenance, and timed proxy

Current positive signals:

- `gem5_integration/systemc_model/src/standalone_test.cpp` emits non-claims such
  as `no_real_gem5_bridge_claim` for standalone/proxy contexts.
- Backend environment plumbing separates request `systemc_config` from resolved
  input refs and exposes bridge paths only when present.

Remaining review risks:

- Bridge provenance must identify whether metrics came from standalone SystemC,
  gem5 smoke, gem5 timed proxy with explicit bridge, or a preserved invalid
  direct report. The same metric names mean different things at different
  ceilings.
- Timed proxy reports must include metric-bearing control/data split: host MMIO,
  polling/interrupt counts, queue wait, SystemC compute time, DMA read/write,
  backpressure, and byte counts.

Required documentation wording:

> A metric-bearing SystemC B2 report is datapath/proxy evidence. A metric-bearing
> B4 report is host/runtime plus SystemC-bridge proxy evidence. Neither one is
> QE-equivalent correctness, RTL cycle accuracy, nor board/physical performance.

### Lane 6: Verification and review gates

Minimum verification set for this closure:

1. Type/compile check for Python modules: `python -m compileall backend docs/benchmarks`.
2. Focused frontend/backend contract tests covering Stage-B0 descriptors,
   SystemC feedback, B3 smoke ingest, B4 hard gate, and release bundles.
3. Documentation grep for forbidden public-claim language in changed docs.
4. Manual review that any refused B4 report is described as a gate refusal, not a
   B4 execution pass.

## 3. Claim-language guardrail

Use these phrases:

- "descriptor-only", "Stage-A/B0 handoff", "timed-functional proxy",
  "metric-bearing proxy report", "gem5 smoke control-path evidence",
  "B4 refusal report", "B4 timed-proxy report with explicit bridge evidence".

Do not use these phrases unless a separate validated artifact exists:

- "QE-equivalent performance", "numerically equivalent SCF", "cycle accurate",
  "RTL/HLS performance", "board speedup", "ASIC/physical FPGA PPA",
  "production-ready winner", "real gem5 pass" for a refusal report.

## 4. Integration checklist for the next merge

- [x] Baseline F2 artifacts keep `architecture_template_ref`, `mapping_ref`, and
      executable `systemc_config` distinct.
- [x] SystemC B2 reports include metrics and non-claims; descriptor-only rows are
      not promoted as executed.
- [x] FPGAAccelerator SimObject params, config script options, environment mode,
      and report mode are aligned.
- [x] B4 runner refuses missing bridge refs and missing bridge artifacts.
- [x] B4 accepted reports include required control-path and host/SystemC/DMA
      metrics.
- [x] Bridge provenance distinguishes standalone, smoke, timed proxy, explicit
      bridge, and invalid-preserved report paths.
- [x] Feedback ingest never raises claim ceilings.
- [x] Release/E2E package emits a claim ceiling matrix, and release bundle /
      status artifacts forbid final winner or production-readiness claims.

## 5. 2026-04-30 Option A+ B4 materialization closure

Implementation closure for the real-gem5/B4 gate added producer-side B4 request
materialization in `tools/benchmarks/run_qe_fpga_dse_e2e_v0.py` without changing
the request/report schema:

- B4-added refs (`gem5_executable`, `gem5_config`,
  `systemc_bridge_library`) are resolved against the repository root before the
  backend runner sees the request.
- Copied Stage-B0 file refs (`application_graph`, `architecture_template`,
  `mapping`, `architecture_config`, `systemc_config`) are resolved against the
  selected Stage-B0 artifact root.
- Scalar/non-path refs remain unchanged, and the original Stage-B0/B2 request
  artifact remains relative/unchanged.
- Bridge provenance comparisons now normalize equivalent filesystem spelling
  while still hard-failing true bridge mismatches.

Current verification evidence after the Top-K/B4 materialization update:

```bash
python3 -m unittest \
  tools.benchmarks.test_run_unified_dse_v0 \
  tools.benchmarks.test_backend_execution_runner \
  tools.benchmarks.test_run_qe_fpga_dse_e2e_v0 \
  tools.benchmarks.test_fpga_accelerator_simobject_contract
```

Result: covered by the later full-suite command in Section 7.

```bash
python3 tools/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/qe_fpga_dse_top2_real_b4_probe \
  --max-design-points 4 \
  --shortlist-size 2 \
  --top-k 2 \
  --b4-top-n 2 \
  --timeout-s 20 \
  --require-real-gem5-b4 \
  --gem5-timeout-s 60 \
  --gem5-executable gem5_integration/gem5/build/X86/gem5.opt \
  --gem5-b4-config gem5_integration/configs/fpga/simple_fpga_test.py \
  --systemc-bridge-library gem5_integration/systemc_model/build/libgem5_systemc_bridge.a
```

Result artifacts:

- `tmp/qe_fpga_dse_top2_real_b4_probe/qe_fpga_dse_e2e_manifest_v0.json`
- `tmp/qe_fpga_dse_top2_real_b4_probe/qe_fpga_dse_performance_summary_v0.json`
- `tmp/qe_fpga_dse_top2_real_b4_probe/backend_report_collection_v0.json`
- `tmp/qe_fpga_dse_top2_real_b4_probe/reranked_results_v0.json`
- `tmp/qe_fpga_dse_top2_real_b4_probe/claim_ceiling_status_matrix_v0.json`
- `tmp/qe_fpga_dse_top2_real_b4_probe/candidate_runs/<candidate>/b4_materialized/backend_execution_request.json`
- `tmp/qe_fpga_dse_top2_real_b4_probe/candidate_runs/<candidate>/b4_materialized/timing_sidecar.json`
- `tmp/qe_fpga_dse_top2_real_b4_probe/candidate_runs/<candidate>/gem5_systemc_timed_proxy_report.json`

The B4 reports are executed `gem5_systemc_timed_proxy_only` timed-proxy reports
with explicit bridge and timing-sidecar provenance. `metrics.gem5_tick_observed`
is preserved as gem5 harness provenance, while `metrics.cycle_proxy` follows the
candidate-specific SystemC timing sidecar so Top-K candidates remain
distinguishable:

- F3 candidate: `cycle_proxy=7360210`, `successful_dma_transfer_bytes=3932160`.
- F2 candidate: `cycle_proxy=9583067`, `successful_dma_transfer_bytes=2949120`.

This closes the materialization bug for repo-relative B4 CLI paths. It does not
raise the claim boundary: there is still no QE numerical-equivalence claim, no
cycle-accuracy claim, and no RTL/HLS/board/ASIC/physical-FPGA performance claim.

## 6. 2026-04-30 Stage C/D evidence and status-matrix closure

Implementation closure for the Stage C/D evidence gap adds producer
materializers and consumer hard gates without changing existing schemas:

- `materialize_qe_stage_c_correctness_v0.py` converts an externally generated
  `qe_gold_gate_summary_v0.json` into per-candidate
  `qe_dse_qe_equivalent_correctness_report_v0` reports plus a
  `stage_c_correctness_matrix_v0.json`.
- `materialize_qe_stage_d_implementation_evidence_v0.py` converts externally
  supplied FPGA/ASIC evidence refs into
  `qe_dse_fpga_asic_implementation_evidence_v0`. Placeholder/template/empty
  evidence is downgraded to `implementation_projection` / `partial`, not
  promoted to HLS/RTL/board/ASIC evidence.
- `run_unified_dse_v0.py` now validates that Stage C/D artifacts join to an
  evaluated candidate, and to a selected candidate when a multi-fidelity plan is
  emitted. Stage D correctness dependencies must match the same Stage C
  candidate/report.
- `run_qe_fpga_dse_e2e_v0.py` passes Stage C/D refs into the frontend when
  provided and always emits `claim_ceiling_status_matrix_v0.json` /
  `claim_ceiling_status_matrix_v0.md` next to the E2E manifest.
- `build_qe_dse_claim_ceiling_status_matrix_v0.py` centralizes the evidence
  status row while keeping `adjudicator_permission_scope=not_evaluated`.

The new central matrix is evidence-status only. It reports the observed ceiling,
for example
`qe_equivalent_scf_correctness_plus_partial_implementation_projection_only`,
and keeps blockers such as `stage_d_implementation_evidence_not_available`
visible. It is not permission to claim cycle accuracy, board speedup, a final
family winner, or production readiness.

Verification evidence:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q backend docs/benchmarks

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tools.benchmarks.test_stage_c_qe_correctness_materializer \
  tools.benchmarks.test_stage_d_implementation_evidence_materializer \
  tools.benchmarks.test_qe_dse_claim_ceiling_status_matrix_v0 \
  tools.benchmarks.test_run_unified_dse_v0 \
  tools.benchmarks.test_run_qe_fpga_dse_e2e_v0 \
  tools.benchmarks.test_backend_execution_runner \
  tools.benchmarks.test_fpga_accelerator_simobject_contract
```

Result at the time of this lane: 84 tests OK. The later Top-K/B4 closure in
Section 7 supersedes this with 85 tests OK after adding the screening-rank and
timing-sidecar regressions.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/qe_fpga_dse_stage_cd_probe \
  --preferred-family F1 \
  --max-design-points 1 \
  --source-kind stub \
  --timeout-s 10 \
  --qe-correctness-report tmp/qe_fpga_dse_stage_cd_evidence/si4_pbe_uspp_small__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition.stage_c.json \
  --implementation-evidence tmp/qe_fpga_dse_stage_cd_evidence/si4_pbe_uspp_small__F1__cpu_only__single_hotpath__fit_first__single_hotpath_partition.stage_d.json \
  --emit-full-stage-status \
  --include-gem5-smoke
```

Result artifacts:

- `tmp/qe_fpga_dse_stage_cd_probe/qe_fpga_dse_e2e_manifest_v0.json`
- `tmp/qe_fpga_dse_stage_cd_probe/qe_fpga_dse_performance_summary_v0.json`
- `tmp/qe_fpga_dse_stage_cd_probe/claim_ceiling_status_matrix_v0.json`
- `tmp/qe_fpga_dse_stage_cd_probe/claim_ceiling_status_matrix_v0.md`

Observed matrix result:

- `final_observed_conclusion_ceiling`:
  `qe_equivalent_scf_correctness_plus_partial_implementation_projection_only`
- `blockers`: `stage_d_implementation_evidence_not_available`

This closes the release-bundle/status-matrix gap. It does not close cycle
accuracy, board measurement, HLS/RTL implementation, ASIC PPA, final public
winner, or production-readiness gates.

## 7. 2026-04-30 Top-K DSE to candidate-specific gem5/SystemC B4 closure

The implemented closed loop now avoids the prior cross-candidate evidence
splicing failure:

1. Unified DSE emits a multi-fidelity plan and Stage-B0 backend requests.
2. The E2E runner selects Top-K candidate requests by `screening_rank`, not by
   descriptor manifest order.
3. Each selected candidate gets a separate B2 `systemc_timed_functional` run
   under `candidate_runs/<candidate>/`.
4. The first `--b4-top-n` ranked candidates get candidate-specific
   `b4_materialized/` artifacts: B4 request, timing sidecar, generated shim, and
   manifest.
5. The backend runner refuses B4 unless the request has an explicit SystemC
   bridge artifact and timing sidecar. The gem5 config receives the sidecar via
   `QEBS_TIMING_SIDECAR_JSON`.
6. The E2E runner writes candidate-aligned `backend_report_collection_v0.json`,
   `reranked_results_v0.json`, and a multi-row
   `claim_ceiling_status_matrix_v0.json`.

Fresh verification command:

```bash
python3 -m compileall -q backend docs/benchmarks gem5_integration/configs

python3 -m unittest \
  tools.benchmarks.test_stage_c_qe_correctness_materializer \
  tools.benchmarks.test_stage_d_implementation_evidence_materializer \
  tools.benchmarks.test_qe_dse_claim_ceiling_status_matrix_v0 \
  tools.benchmarks.test_run_unified_dse_v0 \
  tools.benchmarks.test_run_qe_fpga_dse_e2e_v0 \
  tools.benchmarks.test_backend_execution_runner \
  tools.benchmarks.test_fpga_accelerator_simobject_contract
```

Result: 85 tests OK.

Fresh Top-K/B4 smoke:

```bash
python3 tools/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/qe_fpga_dse_top2_real_b4_probe \
  --max-design-points 4 \
  --shortlist-size 2 \
  --top-k 2 \
  --b4-top-n 2 \
  --timeout-s 20 \
  --require-real-gem5-b4 \
  --gem5-timeout-s 60 \
  --gem5-executable gem5_integration/gem5/build/X86/gem5.opt \
  --gem5-b4-config gem5_integration/configs/fpga/simple_fpga_test.py \
  --systemc-bridge-library gem5_integration/systemc_model/build/libgem5_systemc_bridge.a
```

Observed bounded proxy ranking:

| Observed rank | Candidate | Screening rank | B2 cycle proxy | B4 cycle proxy | B4 bytes moved |
|---:|---|---:|---:|---:|---:|
| 1 | `si4_pbe_uspp_small__F3__cpu_only__single_hotpath__fit_first__single_hotpath_partition` | 1 | 3639 | 7360210 | 3932160 |
| 2 | `si4_pbe_uspp_small__F2__cpu_only__single_hotpath__fit_first__single_hotpath_partition` | 2 | 3639 | 9583067 | 2949120 |

This is a bounded proxy result only. The observed best under this smoke is F3
by the current B4 `cycle_proxy`, but the matrix still reports blockers:
`missing_stage_c_qe_correctness_report` and
`missing_stage_d_implementation_evidence`. Therefore it is not a thesis-grade
architecture winner, not a QE-equivalent SCF result, not a cycle-accurate result,
and not board/HLS/RTL/ASIC evidence.

## 8. 2026-04-30 Ralph closure: per-candidate evidence resolver and timing-source gate

The Ralph-only follow-up closed the remaining trust plumbing without launching a
team runtime:

1. E2E Top-K status matrices now accept repeatable candidate-scoped evidence
   bindings:
   - `--qe-correctness-report-for '<candidate_id>=stage_c.json'`
   - `--implementation-evidence-for '<candidate_id>=stage_d.json'`
2. Each mapped artifact must have an internal `candidate_id` equal to the map
   key. A mismatch is a hard error, so Stage C/D evidence cannot be spliced
   across F2/F3 rows.
3. Legacy singular `--qe-correctness-report` and `--implementation-evidence`
   remain compatible for one-row/exact-match runs, but unmatched singular
   artifacts are treated as absent for other Top-K rows.
4. Stage C materialization can now use an explicit candidate map when old gold
   rows lack `candidate_id`; missing or ambiguous map matches fail loudly.
5. Stage D materialization can now emit a multi-candidate evidence matrix and
   validates per-candidate Stage C dependencies.
6. B4 reports now expose `metrics.cycle_source`. Current simple-gem5 B4 runs
   report `timing_sidecar_projection`, with `gem5_tick_observed` retained as
   provenance. The stricter `gem5_event_timed_device_observed` source is
   rejected unless the report also proves nonzero MMIO activity,
   `event_timed_device_activity_observed=true`, and a positive candidate event
   delta.

Fresh guarded Top-K/B4 run after the Ralph changes:

```bash
python3 tools/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/ralph_dse_evidence_e2e_b4_no_stage_cd \
  --top-k 2 \
  --b4-top-n 2 \
  --max-design-points 8 \
  --require-real-gem5-b4 \
  --gem5-timeout-s 45 \
  --timeout-s 15
```

Observed matrix:

| Candidate | Screening rank | B4 cycle proxy | Cycle source | Event-timed activity | Final ceiling | Blockers |
|---|---:|---:|---|---|---|---|
| `si4_pbe_uspp_small__F3__cpu_only__single_hotpath__fit_first__single_hotpath_partition` | 1 | 7360210 | `timing_sidecar_projection` | false | `gem5_systemc_timed_proxy_only` | `missing_stage_c_qe_correctness_report`, `missing_stage_d_implementation_evidence` |
| `si4_pbe_uspp_small__F2__cpu_only__single_hotpath__fit_first__single_hotpath_partition` | 2 | 9583067 | `timing_sidecar_projection` | false | `gem5_systemc_timed_proxy_only` | `missing_stage_c_qe_correctness_report`, `missing_stage_d_implementation_evidence` |

Current conclusion: F3 is still only the **bounded proxy triage leader** for the
checked Top-2 B4 run. It is not a final architecture winner because Stage C
QE-equivalent correctness and Stage D implementation evidence are still absent
for the promoted F3/F2 candidates, and the B4 cycle number is sidecar-projected
rather than event-timed/cycle-accurate hardware evidence.

Fresh regression command:

```bash
python3 -m compileall -q backend docs/benchmarks gem5_integration/configs

python3 -m unittest \
  tools.benchmarks.test_qe_dse_claim_ceiling_status_matrix_v0 \
  tools.benchmarks.test_stage_c_qe_correctness_materializer \
  tools.benchmarks.test_stage_d_implementation_evidence_materializer \
  tools.benchmarks.test_run_qe_fpga_dse_e2e_v0 \
  tools.benchmarks.test_backend_execution_runner \
  tools.benchmarks.test_fpga_accelerator_simobject_contract \
  tools.benchmarks.test_run_unified_dse_v0
```

Result: 97 tests OK.

## 9. 2026-04-30 Ralph closure: strict gem5 event/tick-observed B4 path

The previous B4 lane was claim-safe but still sidecar-projected. This Ralph
cycle adds and verifies the stricter closed-loop path requested for fast screen
→ detailed simulation:

1. B4 materialization emits `candidate_timing_profile_v0.json` beside the
   timing sidecar and generated SystemC provenance files.
2. The backend runner passes the profile into gem5 with
   `QEBS_CANDIDATE_TIMING_PROFILE_JSON`,
   `QEBS_STRICT_B4_RUNTIME_TIMING_INPUT`, and
   `QEBS_STRICT_B4_EVENT_TIMING=1`.
3. `FPGAAcceleratorSE` now consumes stable strict-event params, schedules
   completion through a gem5 event, counts PIO reads/writes/polls, records
   command/completion ticks, and writes
   `qebs_gem5_fpga_se_event_report_v0`.
4. `simple_fpga_test.py` strict mode runs
   `gem5_integration/qe_test_program/fpga_strict_pio_test` rather than
   `/bin/true`, maps the fixed PIO window in SE mode, and promotes
   `metrics.cycle_source=gem5_event_timed_device_observed` only when the device
   report has nonzero SimObject counters and a positive event delta.

Fresh gem5 build:

```bash
cd gem5_integration/gem5
scons build/X86/gem5.opt -j4
```

Result: build completed; only optional dependency warnings for png, HDF5, and
capstone were emitted.

Direct strict-device smoke used two runtime profiles and proved ordered
candidate deltas:

| Candidate | `cycle_source` | Device event delta ticks | SimObject reads | SimObject writes | Poll reads |
|---|---|---:|---:|---:|---:|
| `candidate_a` | `gem5_event_timed_device_observed` | 200000 | 7 | 3 | 1 |
| `candidate_b` | `gem5_event_timed_device_observed` | 600000 | 8 | 3 | 2 |

Backend-runner strict B4 smoke:

```bash
python3 backend/runners/run_backend_execution_v0.py \
  --request tmp/ralph_strict_b4_backend/request.json \
  --output tmp/ralph_strict_b4_backend/backend_report.json \
  --mode gem5_systemc_timed_proxy \
  --allow-execute \
  --strict-report-validation \
  --timeout-s 120
```

Observed: `execution_status=executed`,
`cycle_source=gem5_event_timed_device_observed`,
`candidate_device_event_delta_ticks=300000`,
`observed_device_activity_source=gem5_simobject_counters`, 8 SimObject reads,
3 writes, and 2 poll reads.

Fresh Top-K strict B4 E2E command:

```bash
python3 tools/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/qe_fpga_dse_event_tick_closed_loop_probe \
  --max-design-points 4 \
  --shortlist-size 2 \
  --top-k 2 \
  --b4-top-n 2 \
  --timeout-s 30 \
  --require-real-gem5-b4 \
  --gem5-timeout-s 120 \
  --gem5-executable gem5_integration/gem5/build/X86/gem5.opt \
  --gem5-b4-config gem5_integration/configs/fpga/simple_fpga_test.py \
  --systemc-bridge-library gem5_integration/systemc_model/build/libgem5_systemc_bridge.a \
  --emit-full-stage-status \
  --claim-ceiling-status-matrix claim_ceiling_status_matrix_v0.json
```

Observed Top-K strict B4 result:

| Candidate | Screening rank | B4 `cycle_source` | Event delta ticks | SimObject reads/writes/polls | Matrix blockers |
|---|---:|---|---:|---|---|
| `si4_pbe_uspp_small__F3__cpu_only__single_hotpath__fit_first__single_hotpath_partition` | 1 | `gem5_event_timed_device_observed` | 7360210 | 23 / 3 / 17 | `missing_stage_c_qe_correctness_report`, `missing_stage_d_implementation_evidence` |
| `si4_pbe_uspp_small__F2__cpu_only__single_hotpath__fit_first__single_hotpath_partition` | 2 | `gem5_event_timed_device_observed` | 9583067 | 27 / 3 / 21 | `missing_stage_c_qe_correctness_report`, `missing_stage_d_implementation_evidence` |

Current conclusion: the requested closed loop now runs through a real gem5
device event/tick-observed proxy for the Top-K B4 candidates. F3 remains the
bounded proxy triage leader for this run. It is still not a final architecture
winner, not QE-equivalent SCF evidence, and not cycle-accurate hardware
evidence until same-candidate Stage C correctness and Stage D implementation
artifacts are supplied and pass the matrix gates.

## 10. 2026-04-30 Final-best architecture evidence-policy closure

A final-best claim now has a separate policy/adjudicator layer instead of
reusing `reranked_results_v0.json` as authority. This is intentionally stricter
than the bounded proxy triage flow.

New decision authority files:

- `tools/benchmarks/final_best_policy_v0.py` defines
  `qe_fpga_final_best_policy_v0`. The v0 default is HLS-synthesis minimum:
  `minimum_stage_d_tier=hls_synthesis`,
  `allow_implementation_projection=false`.
- `tools/benchmarks/build_qe_final_best_architecture_decision_v0.py` emits
  `qe_fpga_final_best_architecture_decision_v0.json` and selects a winner only
  after same-candidate Stage C + Stage D + strict B4 pass.
- `tools/benchmarks/build_qe_candidate_evidence_manifest_v0.py` provides the
  candidate join manifest for external Stage C/D producer lanes.
- `tools/benchmarks/run_qe_stage_c_correctness_for_candidates_v0.py` refuses
  rather than fabricating Stage C when no real gold/QE summary is supplied.
- `tools/benchmarks/stage_d_adapters/hls_synthesis_adapter_v0.py` is the first
  Stage-D adapter; placeholder/template data is still downgraded to projection.

Important claim boundary:

- `reranked_results_v0.json` remains a bounded proxy ranking/triage artifact.
- `qe_fpga_final_best_architecture_decision_v0.json` is the only final-best
  decision artifact.
- A B4-only run must remain `winner=null` even when strict gem5 event ticks are
  observed, because gem5 event ticks do not prove QE numerical correctness or
  implementation maturity.
- The current final-best policy is **final-best-under-HLS-policy**, not board
  measurement, not hardware cycle accuracy, and not ASIC signoff.

Fresh focused verification for this closure is recorded in the final run log of
this Ralph cycle. The expected safe B4-only result is
`decision_status=blocked_no_eligible_candidates` with missing Stage C/D reasons;
a synthetic same-candidate Stage C + HLS Stage D + strict B4 fixture selects a
winner under the HLS policy.

## 11. 2026-05-01 Evidence-plane v1 release claim-boundary closure

The complete-architecture DSE lane adds a release checker so human-facing docs
and machine-readable release reports preserve the new evidence-plane v1 claim
boundaries. The checker is a guardrail around wording and report structure; it
does not promote any candidate by itself.

Normative evidence-tier labels are exact strings:

| Evidence tier | Meaning | Release boundary |
|---|---|---|
| `survey-catalog` | Provenance-backed researched microarchitecture or design-axis entry. | May appear in broad survey coverage only; it is not executable ranking evidence and cannot name a final best. |
| `projection-screened` | Fast/proxy/estimated row that has passed explicit screening assumptions. | May inform Level-1 shortlist discussion, but cannot be a final-best winner or GPU/board/ASIC claim. |
| `systemc-cycle-accounted` | Same candidate/workload has generated/configured SystemC cycle-accounted evidence with per-stage/per-component cycle tables and artifact refs. | Must cite `systemc_cycle_evidence_ref` and `systemc_cycle_evidence_hash`; it remains model-level accounting, not RTL/cycle-accurate or physical timing evidence. |
| `final-best-eligible` | Same candidate has Stage C correctness, strict B4 gem5/SystemC event evidence, generated SystemC cycle-accounted evidence, frozen catalog membership, dominance closure, and Stage D implementation evidence when the active final-best policy requires it. | Only this tier may enter the final-best policy; under `systemc_b4_minimum`, missing Stage D/HLS is recorded as a residual risk, while missing Stage C, strict B4, SystemC, catalog freeze, or dominance closure still yields `winner=null` / blockers. |

Release checker:

```bash
python3 tools/benchmarks/check_qe_dse_release_claim_boundaries_v0.py
```

The checker scans this review, the complete architecture-family DSE framework
doc, and any optional JSON/Markdown report paths passed on the command line. It
fails on catalog/projection final-best overclaims, unguarded SystemC
cycle-accuracy or physical-timing wording, unguarded CPU+FPGA-over-GPU
superiority wording, board/ASIC measured-performance wording without explicit
artifact boundaries, unknown evidence-tier labels, lower-tier JSON winner flags,
and missing SystemC cycle evidence artifact refs for `systemc-cycle-accounted`
or `final-best-eligible` rows.

Current release posture remains conservative and policy-aware:

- The HLS-minimum policy still requires Stage D implementation evidence for a
  final-best result.
- The `systemc_b4_minimum` policy can select a closed-catalog-best result
  without Stage D only when same-candidate Stage C, strict B4, generated SystemC
  cycle evidence, frozen catalog membership, and dominance closure all pass.
- A `systemc-cycle-accounted` row must carry generated SystemC artifacts such as
  `systemc_cycle_evidence_ref`, `systemc_cycle_evidence_hash`, template/config
  hash, per-stage/per-component cycle table refs, calibration refs, and
  non-claims.
- A `final-best-eligible` row must carry same-candidate `stage_c_report_ref`,
  `strict_b4_report_ref`, `systemc_cycle_evidence_ref`,
  catalog-freeze/dominance evidence, and `stage_d_report_ref` only when the
  selected policy requires Stage D before the final-best policy may select it.
- Synthetic positive fixtures may test policy plumbing only when labeled
  synthetic/non-real-world; they do not create a real architecture winner.

This closes the docs/pro_work release-boundary gap for the evidence-plane v1
implementation. It still does not claim QE whole-application superiority over
GPU, board-measured speedup, ASIC signoff, RTL cycle accuracy, physical timing,
or production readiness.

## 12. 2026-05-01 closed-catalog-best `systemc_b4_minimum` evidence closure

The Ralph-only closed-catalog-best loop now has one bounded winner under the
explicit `qe_fpga_final_best_policy_systemc_b4_minimum_v0` policy. This is not a
global architecture optimum and not a board/RTL/ASIC/physical-timing result; it
is the best candidate inside the frozen competitive/evaluable catalog partition
for the checked `si8_pbe_uspp` run and evidence policy.

Winner:

- candidate:
  `si8_pbe_uspp__F2__device_first_fallback__balanced__fit_first__single_hotpath_partition`
- catalog entry: `systolic_fpga_dense_path`
- catalog partition: `competitive_evaluable`
- policy: `qe_fpga_final_best_policy_systemc_b4_minimum_v0`
- evidence tier: `final-best-eligible`
- strict B4 event/tick evidence:
  `candidate_device_event_delta_ticks=9583067`,
  `cycle_source=gem5_event_timed_device_observed`
- residual risk:
  `missing_optional_stage_d_hls_or_stronger_evidence`

Primary release artifacts from the final pass:

- `tmp/closed_catalog_best_si8_top40_pass5/qe_fpga_dse_e2e_manifest_v0.json`
  (`sha256=6ceebff32daeee38d0c3df9f9db9af54ff5dca51e3ddab9891b14bd2bffcaa83`)
- `tmp/closed_catalog_best_si8_top40_pass5/qe_fpga_dse_performance_summary_v0.json`
  (`sha256=43decdb0fdfdd4222ed0c3802775060cc9a3e3df72b6f608f91c83a0df36b578`)
- `tmp/closed_catalog_best_si8_top40_pass5/claim_ceiling_status_matrix_v0.json`
  (`sha256=24f3a52061ddcbe8090847571b49b4a23c0d48aacd77d222f0cef7be872c9f7f`)
- `tmp/closed_catalog_best_si8_top40_pass5/reranked_results_v0.json`
  (`sha256=64700d77a6b749a51de6fcb90cb3eaa9ac4a8bf0a175085b672e63894a5cd28c`)
- `tmp/closed_catalog_best_si8_top40_pass5/qe_fpga_final_best_architecture_decision_v0.json`
  (`sha256=63d09cb02f51cd5a7074b7b61e72136ff5bc590024f0ee85d8f35d38bbf948c1`)
- catalog freeze:
  `docs/benchmarks/qe_microarchitecture_catalog_freeze_manifest_v0.json`
  (`sha256=381e3ce843d510d14820f5db5f767ab5f22055a8dd10e40c9fcefe967e3d435a`)
- policy:
  `docs/benchmarks/qe_final_best_policy_systemc_b4_minimum_v0.json`
  (`sha256=0e08de8c370b6214e3f1d88c0835abd9972e418f88fcc817a18f6645c9c95919`)

Winner same-candidate evidence hashes in the decision artifact:

- Stage C report:
  `6542ad9ca6845da6022ed52f57b0368f76b0175132c99024713bd1929eb17621`
- strict B4 report:
  `b2ea10fa27ef22e2d6bd9e5fbc9877fecf69d06e6516f09fa102e120097468dc`
- SystemC cycle-accounted evidence:
  `0f7d9bad1b61bc36259a6edcf038481de17c5383070ca3535ebedfddc27a60fd`
- Stage D report: absent by policy; recorded as
  `missing_optional_stage_d_hls_or_stronger_evidence`

The dominance closure is intentionally stronger than “highest fixable
candidate.” Higher screening-ranked competitive F3 candidates are represented in
the Top-K queue and final decision ranking table. They do not block the F2
winner because their same-candidate Stage C reports are resolved as
`stage_c_qe_equivalent_scf_not_proven`, not merely missing/unresolved. Missing
Stage C for lower-ranked or nonwinner rows remains visible in
`top_k_closure.blockers`; those blockers are queue diagnostics and do not
override the final decision’s passed dominance closure for the selected winner.

Fresh final E2E command shape:

```bash
python3 tools/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --workload tmp/si8_workload.json \
  --output-dir tmp/closed_catalog_best_si8_top40_pass5 \
  --max-design-points 270 \
  --shortlist-size 40 \
  --top-k 40 \
  --b4-top-n 40 \
  --include-gem5-b4 \
  --require-real-gem5-b4 \
  --timeout-s 20 \
  --gem5-timeout-s 120 \
  --emit-final-best-decision \
  --final-best-policy docs/benchmarks/qe_final_best_policy_systemc_b4_minimum_v0.json \
  --catalog-freeze-manifest docs/benchmarks/qe_microarchitecture_catalog_freeze_manifest_v0.json \
  --qe-correctness-report-for <candidate=stage_c_report> ... \
  --systemc-cycle-evidence-for <candidate=systemc_cycle_report> ...
```

Fresh release-boundary validation for the emitted JSON reports:

```bash
python3 tools/benchmarks/check_qe_dse_release_claim_boundaries_v0.py --no-require-doc-language \
  tmp/closed_catalog_best_si8_top40_pass5/qe_fpga_final_best_architecture_decision_v0.json \
  tmp/closed_catalog_best_si8_top40_pass5/qe_fpga_dse_performance_summary_v0.json \
  tmp/closed_catalog_best_si8_top40_pass5/claim_ceiling_status_matrix_v0.json \
  tmp/closed_catalog_best_si8_top40_pass5/reranked_results_v0.json
```

Expected result: PASS. This checker enforces the same no-overclaim boundary as
the human docs: no global best, no GPU superiority, no synthetic-final evidence,
no Stage C bypass, no RTL/cycle-accurate/physical timing, and no board/ASIC/FPGA
measurement claim.
