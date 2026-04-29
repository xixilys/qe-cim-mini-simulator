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

- `docs/benchmarks/unified_dse/domain_contracts.py` defines domain-neutral IR
  names (`ApplicationGraphIR`, `ArchitectureTemplateIR`, `MappingIR`,
  `EvidenceIR`) and keeps backend reports claim-ceiling validated by fidelity.
- `docs/benchmarks/unified_dse/stage_b0_descriptors.py` emits separate sidecars
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

- [ ] Baseline F2 artifacts keep `architecture_template_ref`, `mapping_ref`, and
      executable `systemc_config` distinct.
- [ ] SystemC B2 reports include metrics and non-claims; descriptor-only rows are
      not promoted as executed.
- [ ] FPGAAccelerator SimObject params, config script options, environment mode,
      and report mode are aligned.
- [ ] B4 runner refuses missing bridge refs and missing bridge artifacts.
- [ ] B4 accepted reports include required control-path and host/SystemC/DMA
      metrics.
- [ ] Bridge provenance distinguishes standalone, smoke, timed proxy, explicit
      bridge, and invalid-preserved report paths.
- [ ] Feedback ingest never raises claim ceilings.
- [ ] Release bundle includes a claim ceiling matrix and forbids final winner /
      production-readiness claims.
