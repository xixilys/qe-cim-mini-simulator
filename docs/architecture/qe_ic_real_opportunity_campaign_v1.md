# QE-IC Real Opportunity Campaign v1

## Purpose

This campaign answers one bounded question: under a real GPU-only baseline, do
FPGA-only or GPU+FPGA hybrid candidates have an opportunity for selected QE-IC
cases?

The campaign is an orchestration layer. It does not define a new DSE objective
and does not replace the existing real-baseline opportunity claim gate. It
connects environment discovery, case preparation, Layer-4 candidate selection,
real/ingested evidence, implementation quality audit, and final interpretation.

## Flow

1. Probe local GPU, QE, profiler, SystemC, and EDA availability.
   In `execute_real` mode, QE discovery records executable path, probe run
   status, version when parseable, GPU-support signal when detectable, and a
   hash of the probe output.
2. Prepare `ground_state_band_structure` and `electron_phonon_mobility` case
   descriptors. Input decks may come from config paths, configured search
   roots, local testdata/examples, experiment directories, or common QE example
   roots. Missing input decks are marked `input_deck_missing`; generated
   templates are placeholders only and are not scientific input data.
3. In `execute_real` mode, attempt a CPU-only QE baseline when cases and QE are
   runnable. This is timing context only and is reported separately from the
   GPU baseline.
4. Build a GPU-only baseline from at least three real GPU-capable QE runs, or
   ingest a validated GPU-baseline artifact. Real runs write stdout/stderr logs
   and output hashes under `runs/<case_id>/gpu_only_baseline/`. A CPU-only QE
   binary is reported as `gpu_qe_binary_cpu_only`; CPU results must not
   substitute for GPU-only evidence. Generated benchmark cases with missing
   pseudopotentials report
   `gpu_qe_execution_unavailable_due_to_pseudopotential` rather than fake QE
   runtime.
5. Select up to three candidates from the existing Layer-4 candidate plan only:
   FPGA FFT/streaming, hybrid reduction sidecar, and hybrid DMA/memory staging.
6. Try candidate evidence in order: ingest configured evidence, trace replay
   from real profile data, SystemC timing, then EDA resource/timing from
   explicit design artifacts. If no trace, runner, or design binding exists,
   the campaign records `blocked_by_missing_candidate_evidence`; it does not
   fabricate SystemC, Vivado, or DC results.
   Configured execution commands must write a complete candidate evidence JSON
   artifact. The campaign records stdout/stderr logs and hashes, validates the
   JSON, and then calls the existing claim gate. It never parses stdout into
   performance numbers.
7. Call the existing real GPU-baseline opportunity analysis package.
8. Audit whether losses are implementation-limited, fundamentally unattractive,
   invalid, evidence-missing, or inconclusive.
9. Emit a plain final answer with missing evidence and next actions.

## Modes

`safe_template` is the default CLI behavior. It preserves the prepared harness:
no real QE commands run, no fake evidence is emitted, and missing inputs/tools
lead to `evidence_missing`.

`execute_real` is selected with `--execute-real`. It attempts environment
probing, QE/input-deck discovery, repeated GPU baseline execution when a real
deck and executable are available, candidate evidence ingestion/attempt
recording, and claim-gate analysis only when both baseline and candidate
evidence are valid.

`nonblocking` is selected with `--nonblocking --allow-generated-inputs`. It
continues when real input decks, traces, SystemC configs, or candidate designs
are missing by generating benchmark/proxy inputs and non-claimable proxy
candidate evidence. Missing decks and missing candidate evidence become
fallback reasons, not terminal statuses. GPU/QE execution failure and required
EDA execution failure remain allowed terminal failures.

Generated QE cases are marked `case_origin=generated_benchmark` and
`scientific_claim_scope=performance_benchmark_only`. They are benchmark/proxy
workloads, not real device-property or mobility science results.

Candidate execution can be configured under `candidate_evidence_execution`
with `trace_replay`, `systemc_timing`, or `eda_resource_timing` entries. Each
entry supplies a command, an `output_json` path, tool name, and version. The
output JSON must already satisfy the candidate high-fidelity evidence schema,
including workflow-level timing, resource/timing fields, and explicit
provenance. Failed commands remain evidence-missing and cannot create a
superiority claim.

The canonical command is:

```bash
python3 dse_v2/scripts/dse/run_qe_ic_real_opportunity_campaign.py \
  --config dse_v2/testdata/qe_ic_real_opportunity/qe_ic_real_opportunity_campaign_config_template.json \
  --out artifacts/qe_ic_real_opportunity_campaign_real_run \
  --execute-real \
  --allow-generated-inputs \
  --nonblocking
```

## Evidence Boundary

Missing tools or missing inputs are valid campaign outcomes. They produce
`evidence_missing` or blocked status, not fabricated measurements. Templates,
L1 estimates, and synthetic feedback labels are search/progress evidence only.

Runtime may be real while profiler-derived metrics are unavailable. Missing GPU
utilization, memory bandwidth utilization, host-device transfer time, and
communication time must be represented as `null` with
`metric_availability.<field> = "unavailable"`, never as `0.0 measured`.

The campaign may report `opportunity_found` only when the existing claim gate
returns a claim-allowed FPGA or hybrid opportunity record.

`execute_real` emits additional small evidence summaries:

- `qe_ic_cpu_baseline_measurements_real_run.json`
- `qe_ic_gpu_baseline_measurements_real_run.json`
- `qe_ic_candidate_high_fidelity_results_real_run.json`

When evidence is unavailable these files contain blocker summaries rather than
measured results.

## Allowed Conclusions

- `opportunity_found`
- `implementation_limited`
- `fundamental_no_opportunity`
- `proxy_only_inconclusive`
- `gpu_or_eda_failure`
- `evidence_missing`
- `blocked_by_missing_qe`
- `blocked_by_missing_input_deck`
- `blocked_by_missing_candidate_evidence`
- `inconclusive`

In nonblocking mode, final campaign statuses are constrained to the
nonblocking status set: `completed_real_claimable`, `completed_proxy_only`,
`completed_implementation_limited`, `completed_no_opportunity`,
`gpu_execution_failed`, `eda_execution_failed`, or
`software_validation_failed`.

## Forbidden Conclusions

The campaign must not claim FPGA-only or GPU+FPGA superiority from EDA tool
availability, templates, fixed candidates, L1 estimates, synthetic labels,
kernel-only evidence, or fixture records.
