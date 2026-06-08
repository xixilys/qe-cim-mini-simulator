cat > /tmp/qe_ic_nonblocking_real_opportunity_campaign_goal.md <<'EOF'
Implement non-blocking QE-IC GPU-vs-FPGA/hybrid opportunity campaign.

Branch:
feature/generic-dse-framework

Remote:
origin/feature/generic-dse-framework

User requirement:
The campaign must not stop merely because input decks, traces, SystemC configs, candidate RTL/HLS designs, or real device cases are missing.

The only allowed terminal blockers are:
1. GPU/QE execution itself fails or is unavailable.
2. EDA execution itself fails or is unavailable when EDA evidence is required.
3. Repository/software validation failure.

Everything else must be handled by automatic generation, fallback, proxy modeling, or lower-confidence evidence.

Main question:
Under an executable benchmark or real QE case, do FPGA-only or GPU+FPGA hybrid candidates have opportunity against GPU-only?

If performance is poor, classify:
- implementation_limited,
- fundamental_no_opportunity,
- proxy_only_inconclusive,
- gpu_or_eda_failure,
- opportunity_found.

Important:
Do NOT fabricate measured performance.
Do NOT call generated/proxy evidence real measurement.
Do NOT make strong GPU-vs-FPGA superiority claims unless existing claim gate passes.
But DO continue the campaign using generated benchmark/proxy/stub evidence whenever possible.

---

# 1. Replace blocking policy

Current campaign may stop at:

- blocked_by_missing_input_deck
- blocked_by_missing_candidate_evidence
- blocked_by_missing_systemc
- eda_ready_but_design_artifact_missing

Change this behavior.

These are no longer terminal blockers.

Instead:

## Missing input deck

Automatically generate small QE benchmark input decks.

Allowed generated cases:
- generated_silicon_scf_pw_v0
- generated_silicon_band_or_nscf_pw_v0
- generated_epw_proxy_v0 if full EPW is unavailable

Mark:
case_origin = generated_benchmark
scientific_claim_scope = performance_benchmark_only

Do not claim real device physics.

## Missing pseudopotential

Search local pseudo paths.
If missing, generate a clear pseudo_missing status.

If no pseudopotential exists, attempt a dry/proxy benchmark path only if QE cannot run physically.
But if QE baseline cannot execute because pseudo is missing, classify terminal blocker as:
gpu_qe_execution_unavailable_due_to_pseudopotential

Do not fake QE runtime.

## Missing candidate design artifact

Automatically generate minimal candidate implementation stubs for selected Layer-4 candidates.

Generate only simple, clearly scoped stubs:

- fpga_fft_transpose_pipeline_stub
- hybrid_reduction_sidecar_stub
- hybrid_dma_or_memory_staging_stub

Allowed forms:
- HLS C/C++ stub if Vivado HLS is available.
- RTL/SystemVerilog stub if VCS/Vivado flow is available.
- SystemC/proxy stub if SystemC runner is available.
- analytical trace-proxy if no design compiler path exists.

Mark:
implementation_maturity = generated_stub
evidence_level = generated_proxy | eda_stub_resource_timing | trace_proxy
claim_strength = none unless claim gate passes with eligible evidence.

## Missing profile/trace

Generate trace proxy from QE runtime and candidate motif profile.
Mark:
trace_origin = generated_from_qe_runtime_and_layer2_profile
evidence_status = proxy_estimate
not measured.

---

# 2. New campaign status semantics

Allowed final statuses:

- completed_real_claimable
- completed_proxy_only
- completed_implementation_limited
- completed_no_opportunity
- gpu_execution_failed
- eda_execution_failed
- software_validation_failed

Do not use:
- blocked_by_missing_input_deck
- blocked_by_missing_candidate_evidence
as final statuses.

They may appear only as internal fallback reasons.

---

# 3. Execution requirements

When invoked with:

python3 dse_v2/scripts/dse/run_qe_ic_real_opportunity_campaign.py \
  --config dse_v2/testdata/qe_ic_real_opportunity/qe_ic_real_opportunity_campaign_config_template.json \
  --out artifacts/qe_ic_real_opportunity_campaign_real_run \
  --execute-real \
  --allow-generated-inputs \
  --nonblocking

The system must attempt the following sequence:

1. Probe GPU.
2. Probe QE.
3. If no input deck exists, generate benchmark input deck.
4. Run CPU baseline if possible.
5. Run GPU baseline if possible.
6. If GPU baseline fails due to QE/GPU execution problem, stop with gpu_execution_failed.
7. Select candidates from Layer-4 only.
8. If no candidate design exists, generate candidate implementation stubs.
9. Probe EDA tools.
10. If EDA tools work, attempt stub resource/timing compilation.
11. If EDA tools fail, stop with eda_execution_failed only if EDA was required for the chosen evidence path.
12. If EDA path is unavailable but GPU baseline exists, generate trace/proxy candidate evidence.
13. Run implementation audit.
14. Run existing opportunity claim gate only when evidence is eligible.
15. Produce final report.

---

# 4. Generated QE benchmark cases

Codex must implement automatic generated case support.

Generated input decks must be valid QE syntax when possible.

Minimum generated case:
- pw.x silicon SCF or small semiconductor proxy

Metadata required:
- case_id
- workload_family_id
- program
- input_deck_path
- input_deck_hash
- case_origin = generated_benchmark
- scientific_claim_scope = performance_benchmark_only
- pseudo_file_path if used
- pseudo_hash if used

If full EPW is too hard:
generate:
- electron_phonon_mobility_proxy
not full mobility.

Must clearly state:
This is a benchmark/proxy workload, not a real mobility science result.

---

# 5. CPU and GPU baseline

Codex must run baseline when possible.

CPU baseline:
- run CPU QE path if possible.
- if only one QE binary exists, attempt CPU mode through environment variables or command options.
- at least 3 runs when feasible.

GPU baseline:
- run GPU-enabled QE path if available.
- if QE binary appears CPU-only, report gpu_qe_binary_cpu_only.
- do not pretend CPU result is GPU result.

Metrics:
- runtime is measured from command execution.
- optional telemetry may be unavailable.
- unavailable telemetry must be null/unavailable, never fake 0.0 measured.

---

# 6. Candidate implementation stubs

For the selected Layer-4 candidates, generate minimal stubs.

Stub rules:

## fft_transpose candidate

Generate:
- streaming transpose or memory reorder stub,
- parameterized dimensions,
- simple input/output stream or array interface.

## reduction sidecar

Generate:
- tree reduction stub,
- configurable width,
- simple valid-ready or memory interface.

## DMA/memory staging sidecar

Generate:
- buffering / double-buffer / staging stub,
- no fake DMA performance claim.

The generated stubs only support:
- implementation feasibility,
- rough resource/timing evidence,
- implementation-quality diagnosis.

They do not prove final acceleration.

---

# 7. EDA execution

Use detected EDA tools when available.

Known possible remote alias:
ic-eda

Known tools:
- dc_shell: /home/synopsys/syn/O-2018.06-SP1/bin/dc_shell
- vcs: /home/synopsys/vcs-mx/O-2018.09-1/bin/vcs
- vivado: /home/Xilinx/Vivado/2019.1/bin/vivado

The setlocale warning:
setlocale: LC_ALL: cannot change locale (C.UTF-8)
must not fail the probe if tool version command succeeds.

EDA evidence may include:
- syntax check,
- simulation compile,
- resource/timing estimate,
- synthesis failed with reason.

If EDA fails because the tool itself cannot run:
final status may be eda_execution_failed.

If EDA runs but design fails:
do not block.
Classify candidate as implementation_limited or resource/timing invalid.

---

# 8. Candidate evidence hierarchy

Evidence levels:

1. measured_real_qe
2. trace_replay_from_real_profile
3. systemc_timing
4. eda_stub_resource_timing
5. generated_trace_proxy
6. l1_estimate_only

Strong opportunity claims require existing claim gate eligibility.

Proxy evidence can produce:
- implementation_limited,
- proxy_only_inconclusive,
- likely_no_opportunity_proxy,
but not strong opportunity_found.

If candidate evidence is generated_stub/proxy, final answer must explain that it is not final measured performance.

---

# 9. Implementation audit

This is mandatory.

If candidate loses to GPU but the implementation is generated_stub/proxy/unoptimized:
classify:
implementation_limited
or proxy_only_inconclusive

Do not classify fundamental_no_opportunity unless all are true:
- GPU baseline measured.
- Candidate workflow-level evidence exists.
- Evidence is not just generated proxy.
- Implementation quality gate passes.
- Resource/timing known.
- Idealized upper bound <= 1.0.
- Existing claim gate does not pass.
- No missing evidence is responsible.

If actual/proxy result loses but idealized upper bound > 1.0:
classify:
implementation_limited.

---

# 10. Final report answer

Final answer must be direct.

Examples:

## GPU/QE fails

"Campaign could not answer the question because GPU/QE execution failed. This is an allowed terminal blocker."

## GPU baseline runs but candidate evidence is generated proxy

"Generated QE benchmark ran on GPU. Candidate evidence is generated proxy/stub only, so no strong GPU-vs-FPGA claim is allowed. The current result is proxy_only_inconclusive or implementation_limited."

## Candidate stub fails EDA

"GPU baseline ran, but generated FPGA stub failed EDA synthesis/timing. This indicates implementation_limited/resource_invalid, not fundamental no opportunity."

## Candidate passes eligible claim gate

"Candidate X passes the claim gate with Yx speedup versus GPU-only on generated benchmark case C. This is a performance benchmark claim only, not a real device-property claim."

---

# 11. Validation

Validator must enforce:

- nonblocking mode cannot finish with blocked_by_missing_input_deck.
- nonblocking mode cannot finish with blocked_by_missing_candidate_evidence.
- generated benchmark cases are marked performance_benchmark_only.
- CPU baseline is not substituted for GPU baseline.
- missing telemetry is not fake 0.0 measured.
- generated/proxy evidence cannot produce strong opportunity claim.
- fundamental_no_opportunity cannot be produced from generated proxy/stub evidence.
- opportunity_found requires existing claim gate pass.
- EDA tool failure is distinguished from design failure.
- final answer matches evidence level and implementation audit.

---

# 12. Tests

Add/update tests:

- nonblocking mode generates input deck when missing.
- nonblocking mode does not stop at input_deck_missing.
- nonblocking mode generates candidate stubs when design artifacts are missing.
- generated proxy evidence cannot make strong claim.
- missing telemetry remains unavailable/null.
- CPU baseline cannot replace GPU baseline.
- EDA tool unavailable can produce eda_execution_failed.
- EDA design failure produces implementation_limited/resource_invalid, not software failure.
- fundamental_no_opportunity impossible with generated proxy evidence.
- implementation_limited when generated stub loses but idealized upper bound > 1.
- opportunity_found only when existing claim gate passes.
- CLI supports --nonblocking.
- real-run artifact drift passes.
- full relevant suite passes.

Run:

python3 -m pytest -q dse_v2/tests/test_qe_ic_real_opportunity_campaign.py

python3 -m pytest -q \
  dse_v2/tests/test_qe_ic_workload_suite.py \
  dse_v2/tests/test_qe_ic_motif_profile.py \
  dse_v2/tests/test_qe_ic_target_viability.py \
  dse_v2/tests/test_qe_ic_candidate_plan.py \
  dse_v2/tests/test_qe_ic_l1_cost_model.py \
  dse_v2/tests/test_qe_ic_feedback_calibration.py \
  dse_v2/tests/test_qe_ic_closed_loop_dse.py \
  dse_v2/tests/test_qe_ic_real_baseline_opportunity.py \
  dse_v2/tests/test_qe_ic_real_opportunity_campaign.py

Compile:

python3 -m compileall \
  dse_v2/experiments/qe_ic_real_opportunity \
  dse_v2/scripts/dse/run_qe_ic_real_opportunity_campaign.py

---

# 13. Actually run nonblocking campaign

Run:

python3 dse_v2/scripts/dse/run_qe_ic_real_opportunity_campaign.py \
  --config dse_v2/testdata/qe_ic_real_opportunity/qe_ic_real_opportunity_campaign_config_template.json \
  --out artifacts/qe_ic_real_opportunity_campaign_real_run \
  --execute-real \
  --allow-generated-inputs \
  --nonblocking

Expected:
- It must not stop just because input deck is missing.
- It must not stop just because candidate design is missing.
- It should generate benchmark inputs/stubs/proxy evidence where needed.
- It should only stop terminally if GPU/QE or EDA execution itself fails.

---

# 14. Git

Before starting:
git status --short

Do not commit unrelated dirty files.

Before commit:
- run tests,
- run compileall,
- run nonblocking campaign,
- regenerate canonical artifacts,
- do not commit huge raw logs or large pseudo files.

Commit:

git add <only relevant files>
git commit -m "fix: make QE-IC real opportunity campaign nonblocking"

Push:

git push origin feature/generic-dse-framework

Final Codex response must include:
- commit SHA,
- branch,
- push result,
- tests run,
- compileall result,
- nonblocking campaign command result,
- whether generated input deck was created,
- whether CPU baseline ran,
- whether GPU baseline ran,
- whether EDA ran,
- whether candidate stubs/proxy evidence were generated,
- final overall_answer,
- whether any strong superiority claim was made,
- exact reason if terminal failure occurred.

EOF

codex exec < /tmp/qe_ic_nonblocking_real_opportunity_campaign_goal.md
