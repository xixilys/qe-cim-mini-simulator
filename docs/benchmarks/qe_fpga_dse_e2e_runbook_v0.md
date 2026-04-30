# QE FPGA DSE E2E v0 Runbook

This runbook drives the contract-only frontend/backend loop for a small QE-like
workload. It is a proxy/smoke evidence path, not a final FPGA performance or QE
correctness claim.

## Command

```bash
python3 docs/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/qe_fpga_dse_e2e_v0 \
  --top-k 3 \
  --b4-top-n 1 \
  --include-gem5-smoke \
  --include-gem5-b4
```

To attach externally materialized Stage C/D evidence without executing QE,
HLS, RTL, board, or ASIC tools inside the DSE runner:

```bash
python3 docs/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/qe_fpga_dse_e2e_stage_cd_v0 \
  --preferred-family F2 \
  --max-design-points 8 \
  --top-k 3 \
  --b4-top-n 1 \
  --qe-correctness-report tmp/stage_c/stage_c_reports/<candidate>.qe_dse_qe_equivalent_correctness_report_v0.json \
  --implementation-evidence tmp/stage_d/<candidate>.implementation_evidence.json \
  --emit-full-stage-status \
  --include-gem5-smoke \
  --include-gem5-b4
```

The Stage C/D artifacts must already exist. Stage C can be materialized from a
`qe_gold_gate_summary_v0.json`:

```bash
python3 docs/benchmarks/materialize_qe_stage_c_correctness_v0.py \
  --gold-summary tmp/qe_gold_gate_summary_v0.json \
  --output-dir tmp/stage_c
```

Stage D can be materialized from external implementation evidence refs. Template
or placeholder inputs intentionally downgrade to `implementation_projection` /
`partial`:

```bash
python3 docs/benchmarks/materialize_qe_stage_d_implementation_evidence_v0.py \
  --candidate-id <candidate> \
  --output tmp/stage_d/<candidate>.implementation_evidence.json \
  --implementation-target-class fpga \
  --evidence-kind implementation_projection \
  --artifact-ref projection_note=docs/benchmarks/qe_fpga_board_manifest_template_v0.json \
  --metric projected_latency_cycles=42 \
  --qe-correctness-report tmp/stage_c/stage_c_reports/<candidate>.qe_dse_qe_equivalent_correctness_report_v0.json
```

For the real-gem5/B4 hard gate with repo-relative CLI paths:

```bash
python3 docs/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/qe_fpga_dse_e2e_real_b4_relpath_verify \
  --preferred-family F2 \
  --max-design-points 8 \
  --top-k 3 \
  --b4-top-n 1 \
  --timeout-s 10 \
  --require-real-gem5-b4 \
  --gem5-timeout-s 60 \
  --gem5-executable gem5_integration/gem5/build/X86/gem5.opt \
  --gem5-b4-config gem5_integration/configs/fpga/simple_fpga_test.py \
  --systemc-bridge-library gem5_integration/systemc_model/build/libgem5_systemc_bridge.a
```

## What it does

1. Runs Unified DSE v0 frontend screening and emits Stage-B0 descriptors.
2. Selects candidate-specific Stage-B0 backend requests from
   `multi_fidelity_plan_v0.json` by `screening_rank`, bounded by `--top-k`.
   `--candidate-id` can override this with one explicit candidate. The older
   `--preferred-family` fallback is used only when no multi-fidelity selection
   is available.
3. Runs backend `systemc_timed_functional` with `--allow-execute` for each
   selected Top-K candidate under `candidate_runs/<candidate>/`.
4. Ingests the candidate-aligned backend report collection back into frontend
   EvidenceIR.
5. Adds B3 `gem5_systemc_smoke` evidence by converting the legacy smoke report by default.
6. Optionally runs B4 `gem5_systemc_timed_proxy` through the real gem5 binary and
   the guarded `simple_fpga_test.py` config. This requires an explicit
   `systemc_bridge_library` artifact and preserves that bridge path in both
   `environment.systemc_bridge` and `artifact_refs.systemc_bridge`. Only the
   first `--b4-top-n` candidates after screening-rank ordering are escalated.
7. When materializing each candidate-specific B4 request, writes
   `candidate_runs/<candidate>/b4_materialized/` with:
   - `backend_execution_request.json`
   - `timing_sidecar.json`
   - `candidate_timing_profile_v0.json`
   - `generated_systemc/<candidate>_candidate_bridge.{hpp,cpp}`
   - `manifest_v0.json`
   The runtime candidate timing profile is the strict B4 event/tick input.
   Generated SystemC is compile/provenance evidence and is not required to
   rebuild gem5 for every candidate.
8. During B4 materialization, resolves only file-like input refs:
   - B4-added `gem5_executable`, `gem5_config`, and `systemc_bridge_library`
     are resolved against the repository root, so repo-relative CLI arguments
     do not become relative to the temporary E2E output directory.
   - B4-added `timing_sidecar` is mandatory and is passed to gem5 as
     `QEBS_TIMING_SIDECAR_JSON`.
   - B4-added `candidate_timing_profile` is passed to gem5 as
     `QEBS_CANDIDATE_TIMING_PROFILE_JSON` and
     `QEBS_STRICT_B4_RUNTIME_TIMING_INPUT`. When present, the backend runner
     also enables `QEBS_STRICT_B4_EVENT_TIMING=1` and provides
     `QEBS_STRICT_B4_DEVICE_EVENT_REPORT_JSON`.
   - Copied Stage-B0 file refs (`application_graph`, `architecture_template`,
     `mapping`, `architecture_config`, `systemc_config`) are resolved against
     the selected Stage-B0 artifact root.
   - Scalar/non-path refs remain unchanged, and the original Stage-B0/B2
     request artifact is not rewritten.
9. Writes:
   - `qe_fpga_dse_e2e_manifest_v0.json`
   - `qe_fpga_dse_performance_summary_v0.json`
   - `backend_report_collection_v0.json`
   - `reranked_results_v0.json`
   - `claim_ceiling_status_matrix_v0.json`
   - `claim_ceiling_status_matrix_v0.md`

When `--qe-correctness-report` or `--implementation-evidence` is present, the
runner preserves legacy single-candidate behavior: the artifact is attached only
to a matching candidate row, or to the sole row when the artifact has no
candidate id. Top-K runs should use repeatable per-candidate bindings instead:

```bash
--qe-correctness-report-for '<candidate_id>=path/to/stage_c.json' \
--implementation-evidence-for '<candidate_id>=path/to/stage_d.json'
```

Each mapped artifact is validated before matrix construction. The JSON
`candidate_id` must exactly match the map key; otherwise the E2E run hard-fails.
Unmatched singular artifacts are treated as absent for other candidates rather
than producing cross-candidate alignment noise. Stage D correctness dependencies
must still point at the same Stage C candidate/report. Mismatches hard-fail
instead of silently becoming evidence.

## Claim boundary

Allowed claims are limited to:

- `systemc_timed_functional_proxy_only` for the SystemC proxy report.
- `gem5_systemc_smoke_only` for the gem5 smoke report.
- `gem5_systemc_timed_proxy_only` for the optional B4 timed-proxy report.
- `qe_equivalent_scf_correctness_only` for an externally executed, validated
  Stage C correctness report.
- The exact Stage D implementation-evidence ceiling (`implementation_evidence_only`,
  `hls_synthesis_only`, `rtl_simulation_only`, `fpga_board_measurement_only`,
  `openroad_physical_estimate_only`, or `asic_ppa_estimate_only`) for an
  externally supplied implementation artifact.

Forbidden claims remain out of scope:

- Hidden QE numerical equivalence / scientific correctness execution by the DSE
  runner. QE equivalence can only be cited through the explicit Stage C report.
- Cycle accuracy.
- Hidden RTL, HLS, board, ASIC, or physical FPGA measurement. Such evidence can
  only be cited through explicit Stage D artifacts and their own ceilings.
- End-to-end acceleration on real FPGA hardware.
- Final public family winner or production readiness.

The central `claim_ceiling_status_matrix_v0.json` is an evidence-status matrix,
not an adjudicator permission matrix. It includes
`adjudicator_permission_scope: not_evaluated` and keeps B2/B3/B4, Stage C, and
Stage D ceilings separate so reviewers do not collapse proxy timing,
correctness-only, and implementation-only evidence into a single performance
claim. It also records candidate alignment so evidence from one candidate cannot
be spliced into another candidate row.

Use `--require-real-gem5-smoke` only when local gem5/QE smoke prerequisites are
available; otherwise the default legacy B3 conversion keeps the run reproducible
without elevating the claim ceiling.

Use `--require-real-gem5-b4` only after `gem5_integration/gem5/build/X86/gem5.opt`
has been rebuilt with the `FPGAAcceleratorSE` strict-event B4 parameters and
`gem5_integration/systemc_model/build/libgem5_systemc_bridge.a` exists. The
hard gate rejects refusal reports, smoke fallbacks, missing bridge provenance,
missing timing-sidecar provenance, and reports without the B4 control/metric
fields.

`reranked_results_v0.json` is a bounded observed-proxy ranking only. It ranks by
B4 `cycle_proxy` when present, otherwise B2 `cycle_proxy`, otherwise screening
rank. If only a subset was escalated to B4, the output is a triage decision aid,
not a final architecture winner. In B4 reports,
`metrics.gem5_tick_observed` records gem5 harness execution provenance, while
`metrics.cycle_proxy` comes from the candidate-specific SystemC timing sidecar
so gem5 boot/exit overhead does not erase candidate timing differences. The
source is explicit:

- `metrics.cycle_source=timing_sidecar_projection` means the cycle proxy is
  sidecar-derived, with gem5 tick retained only as provenance.
- `metrics.cycle_source=gem5_exit_tick` is a fallback harness tick and is not a
  candidate timing conclusion.
- `metrics.cycle_source=gem5_event_timed_device_observed` is accepted only when
  the strict `FPGAAcceleratorSE` device report has nonzero SimObject-observed
  PIO/MMIO reads and writes,
  `event_timed_device_activity_observed=true`, and a positive
  `candidate_device_event_delta_ticks`.

The `/bin/true` simple-gem5 B4 harness therefore remains
`gem5_systemc_timed_proxy_only`; it does not claim event-timed device activity
or cycle accuracy. Strict B4 uses
`gem5_integration/qe_test_program/fpga_strict_pio_test` against
`FPGAAcceleratorSE` at the fixed PIO window. This is a gem5 event-scheduled,
tick-observed device proxy only: it proves that the guest touched the gem5
device and that candidate-specific event delay was observed, not RTL/board
cycle accuracy.

Fresh strict-event Top-K/B4 proof command:

```bash
python3 docs/benchmarks/run_qe_fpga_dse_e2e_v0.py \
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

Observed strict B4 reports:

| Candidate family | B4 `cycle_source` | Event delta ticks | SimObject reads | SimObject writes | Poll reads |
|---|---|---:|---:|---:|---:|
| F3 | `gem5_event_timed_device_observed` | 7360210 | 23 | 3 | 17 |
| F2 | `gem5_event_timed_device_observed` | 9583067 | 27 | 3 | 21 |

The bounded proxy triage leader is F3 for this Top-2 run. The status matrix
still blocks a final architecture recommendation because Stage C QE correctness
and Stage D implementation evidence were not supplied for those same
candidates.

## Final-best decision artifact v0

The E2E runner can now emit a separate final-best decision artifact instead of
renaming the bounded proxy rerank as a winner:

```bash
python3 docs/benchmarks/run_qe_fpga_dse_e2e_v0.py \
  --output-dir tmp/qe_fpga_final_best_probe \
  --max-design-points 4 \
  --shortlist-size 2 \
  --top-k 2 \
  --b4-top-n 2 \
  --require-real-gem5-b4 \
  --gem5-timeout-s 120 \
  --gem5-executable gem5_integration/gem5/build/X86/gem5.opt \
  --gem5-b4-config gem5_integration/configs/fpga/simple_fpga_test.py \
  --systemc-bridge-library gem5_integration/systemc_model/build/libgem5_systemc_bridge.a \
  --qe-correctness-report-for '<candidate_id>=path/to/stage_c.json' \
  --implementation-evidence-for '<candidate_id>=path/to/stage_d.json' \
  --emit-final-best-decision
```

If `--final-best-policy` is omitted, the v0 default policy is
`qe_fpga_final_best_policy_hls_v0`: Stage D must be `hls_synthesis` or stronger
with `evidence_status=available`. `implementation_projection` and `partial`
evidence remain blocked for final-best. The emitted
`qe_fpga_final_best_architecture_decision_v0.json` is the only artifact allowed
to state `winner != null`, and only when the same candidate has:

1. Stage C `qe_equivalent_scf_claim=true`.
2. Stage D evidence satisfying the explicit policy.
3. Strict B4 `metrics.cycle_source=gem5_event_timed_device_observed` with
   nonzero SimObject activity and positive `candidate_device_event_delta_ticks`.

Current B4-only runs should therefore produce `winner=null` and
`decision_status=blocked_no_eligible_candidates`. That is the intended safe
state, not a failure of the final-best gate.

Helper entry points for producer lanes:

```bash
python3 docs/benchmarks/build_qe_candidate_evidence_manifest_v0.py \
  --e2e-manifest tmp/qe_fpga_final_best_probe/qe_fpga_dse_e2e_manifest_v0.json \
  --output tmp/qe_fpga_final_best_probe/qe_candidate_evidence_manifest_v0.json

python3 docs/benchmarks/run_qe_stage_c_correctness_for_candidates_v0.py \
  --candidate-manifest tmp/qe_fpga_final_best_probe/qe_candidate_evidence_manifest_v0.json \
  --output-dir tmp/stage_c_candidates \
  --gold-summary tmp/qe_gold_gate_summary_v0.json

python3 docs/benchmarks/stage_d_adapters/hls_synthesis_adapter_v0.py \
  --candidate-evidence-map tmp/hls_candidate_evidence_map.json \
  --output-dir tmp/stage_d_hls \
  --qe-correctness-report-for '<candidate_id>=tmp/stage_c_candidates/stage_c_reports/<candidate>.qe_dse_qe_equivalent_correctness_report_v0.json'
```

The Stage C wrapper refuses with `stage_c_not_executed` when no real gold/QE
summary is supplied. The HLS adapter downgrades placeholder/template inputs to
`implementation_projection`, so synthetic or incomplete implementation evidence
cannot accidentally trigger a final-best winner.
