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
   status, version when parseable, help-output accelerator signals, dynamic
   GPU library links from `ldd`, and a hash of the probe output. A QE binary is
   GPU-enabled only when both the executable probe and dynamic library probe
   support that conclusion. GPU probing uses a WSL-compatible `nvidia-smi`
   query and records CUDA version from the normal `nvidia-smi` table when
   present. EDA probing checks local PATH and discovered SSH aliases such as
   `ic-eda`; reachable remote Vivado, DC, and VCS tools are recorded in
   `tools.eda.available_tools` as remote paths.
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
   runtime. If a local GPU-QE build probe is present at
   `artifacts/qe_gpu_build/qe_gpu_build_probe.json` or `QE_GPU_BUILD_PROBE`,
   the campaign records its status. A GPU-linked QE build whose `pw.x`,
   `ph.x`, or `epw.x` runtime probes segfault is reported as
   `gpu_qe_build_failed`, not as a usable GPU baseline and not as a GPU-vs-FPGA
   claim.
5. Select up to three candidates from the existing Layer-4 candidate plan only:
   FPGA FFT/streaming, hybrid reduction sidecar, and hybrid DMA/memory staging.
6. Try candidate evidence in order: ingest configured evidence, trace replay
   from real profile data, SystemC timing, then EDA resource/timing from
   explicit design artifacts. In nonblocking `execute_real` mode, if the three
   Layer-4 candidates have no implementation binding, the campaign generates
   minimal RTL/HLS/SystemC stubs and attempts a real EDA syntax run through the
   available local or `ic-eda` tool path. This clears
   `blocked_by_missing_candidate_design` only for the stub-readiness path; it
   does not clear `blocked_by_missing_candidate_evidence` and does not create
   workflow high-fidelity performance evidence.
   Configured execution commands must write a complete candidate evidence JSON
   artifact. The campaign records stdout/stderr logs and hashes, validates the
   JSON, and then calls the existing claim gate. It never parses stdout into
   performance numbers.
7. Call the existing real GPU-baseline opportunity analysis package.
8. Audit whether losses are implementation-limited, fundamentally unattractive,
   invalid, evidence-missing, or inconclusive.
9. Emit a plain final answer with missing evidence and next actions.
10. Attach a seven-day preliminary advisor-facing classification under
    `opportunity_summary.preliminary_classification` and mirror the headline
    fields in `final_answer.preliminary_*`. This label is a triage/reporting
    adapter over the existing claim-gated evidence; it does not change
    claim-gate verdicts and must never upgrade proxy, fixture, L1-only, or
    generated-stub evidence into a final FPGA/hybrid superiority claim.

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
are missing by generating benchmark/proxy inputs, non-claimable proxy candidate
evidence, and generated candidate stubs with EDA syntax-attempt evidence.
Missing decks and missing candidate evidence become fallback reasons, not
terminal statuses. GPU/QE execution failure and required EDA execution failure
remain allowed terminal failures.

Generated QE cases are marked `case_origin=generated_benchmark` and
`scientific_claim_scope=performance_benchmark_only`. They are benchmark/proxy
workloads, not real device-property or mobility science results. For generated
silicon `pw.x` cases, the campaign searches configured pseudo roots, common QE
pseudo directories, and `QE_PSEUDO_DIR`/`ESPRESSO_PSEUDO`/`PSEUDO_DIR` before
classifying the case as `pseudo_missing`.

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

The preliminary classification may report one of the four advisor labels
(`fpga_hybrid_stronger`, `fpga_hybrid_weaker`, `gpu_dominant`, or
`fundamental_no_opportunity`) only when the required baseline/candidate evidence
is present for that preliminary tier. If measured GPU baseline evidence or real
or high-fidelity candidate evidence is missing, the classifier fails closed to
`insufficient_evidence` with `advisor_labels_supported=false`, low confidence,
explicit blockers, and required next evidence. `final_claim_allowed` remains
`false` for all preliminary labels.

EDA tool availability is machine capability only. A remote `ic-eda` tool path
can unlock stub/resource/timing attempts when a candidate design binding exists
or when nonblocking mode generates minimal candidate stubs. The runner sets
`LC_ALL=C LANG=C` for remote EDA tools because Vivado 2019.1 can fail under the
default remote `C.UTF-8` locale. Tool availability or generated-stub syntax
success is not itself synthesis, timing, PPA, or superiority evidence.

The scoped real-hybrid HLS/VCS follow-up campaign writes
`artifacts/qe_ic_real_hybrid_hls/real_hybrid_hls_summary.json`,
`real_hybrid_hls_report.md`, and `real_hybrid_claim_closure.json`. It may
combine multiple VCS-passed handwritten RTL miniapps into
`hybrid_combined_vcs_sidecar_v1` trace-replay accounting by summing the measured
QE timer regions each miniapp maps to and adding explicit launch, transfer, and
synchronization overheads. That combined sidecar row is still
`combined_partial_sidecar_motif` evidence: it is useful for preliminary
sensitivity and architecture ranking, but it does not satisfy full QE kernel
integration or physical FPGA board measurement gates and must not be reported
as final GPU-vs-FPGA superiority.

`execute_real` emits additional small evidence summaries:

- `qe_ic_cpu_baseline_measurements_real_run.json`
- `qe_ic_gpu_baseline_measurements_real_run.json`
- `qe_ic_candidate_high_fidelity_results_real_run.json`
- `qe_ic_candidate_eda_stub_evidence_real_run.json`

When evidence is unavailable these files contain blocker summaries rather than
measured results.

## Allowed Conclusions

- `opportunity_found`
- `implementation_limited`
- `fundamental_no_opportunity`
- `proxy_only_inconclusive`
- `gpu_or_eda_failure`
- `gpu_qe_binary_cpu_only`
- `gpu_qe_build_failed`
- `evidence_missing`
- `blocked_by_missing_qe`
- `blocked_by_missing_input_deck`
- `blocked_by_missing_candidate_evidence`
- `inconclusive`

In nonblocking mode, final campaign statuses are constrained to the
nonblocking status set: `completed_real_claimable`, `completed_proxy_only`,
`completed_implementation_limited`, `completed_no_opportunity`,
`gpu_execution_failed`, `eda_execution_failed`, or
`software_validation_failed`. When the GPU baseline cannot run because QE is
CPU-only or a GPU-enabled QE build fails, the final answer is the precise
`gpu_qe_binary_cpu_only` or `gpu_qe_build_failed` blocker rather than the
generic `gpu_or_eda_failure`.

For the current local machine, the recorded GPU-QE build status is
`gpu_qe_build_failed`: QE 7.5 binaries were built with CUDA/NVHPC/OpenACC
libraries linked, but `pw.x -h`, `ph.x -h`, `epw.x -h`, and version probes
segfault during startup. The report therefore preserves the build evidence
without running or claiming a measured GPU baseline.

## Forbidden Conclusions

The campaign must not claim FPGA-only or GPU+FPGA superiority from EDA tool
availability, templates, fixed candidates, L1 estimates, synthetic labels,
kernel-only evidence, or fixture records.
