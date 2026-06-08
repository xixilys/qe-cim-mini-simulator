# Real Hybrid FPGA Evidence Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace generated-stub/proxy candidate-side evidence with real HLS/RTL hybrid FPGA architectures that produce correctness, simulation, synthesis, and performance evidence strong enough to compare against measured GPU QE full-SCF baselines.

**Architecture:** Keep the DSE control plane domain-neutral and place QE-specific hard evidence under the scoped QE-IC proof path. Use a staged evidence ladder: real generated benchmark/full-SCF GPU baseline -> non-stub HLS/RTL kernels with golden tests -> Vivado-HLS C-sim/C-synth/cosim or VCS RTL simulation -> parsed latency/resource/Fmax -> full-SCF accounting comparison -> claim-gated conclusion. A failed architecture becomes implementation-limited evidence and triggers a different architecture attempt; it is not completion by itself.

**Tech Stack:** Python 3, pytest, Quantum ESPRESSO GPU baseline artifacts, Vivado HLS 2019.1 over `ssh ic-eda`, VCS over `ssh ic-eda`, JSON/Markdown evidence artifacts.

---

### Task 1: Non-Stub Evidence Contract

**Files:**
- Create: `dse_v2/experiments/qe_ic_real_opportunity/real_hybrid_hls_evidence.py`
- Test: `dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py`

- [ ] **Step 1: Write a failing test that rejects stub/proxy evidence**

Create `dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py` with assertions that `build_real_hybrid_architecture_specs()` returns multiple architecture specs with `implementation_maturity="real_hls_kernel"`, non-empty algorithm descriptions, and no `stub`/`proxy` evidence labels.

- [ ] **Step 2: Run the failing test**

Run:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py::test_real_hybrid_specs_are_not_stub_or_proxy
```

Expected: FAIL because the module does not exist yet.

- [ ] **Step 3: Implement minimal specs**

Implement architecture specs for at least:

1. `hybrid_streaming_reduction_accumulator_v1` — GPU retains QE dense work; FPGA sidecar reduces complex partial sums with deterministic fixed dataflow.
2. `hybrid_tiled_complex_axpy_v1` — FPGA sidecar performs tiled complex vector update / memory staging candidate.
3. `hybrid_fft_twiddle_stream_v1` — FPGA sidecar performs stream multiply/reorder motif candidate.

Each spec must declare golden input size, algorithm role, kernel name, target type `gpu_fpga_hybrid`, and why it is a real kernel rather than a stub.

- [ ] **Step 4: Run the test**

Run the same pytest command. Expected: PASS.

### Task 2: Vivado-HLS Runner With Correctness And Latency Evidence

**Files:**
- Modify: `dse_v2/experiments/qe_ic_real_opportunity/real_hybrid_hls_evidence.py`
- Test: `dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py`

- [ ] **Step 1: Write a failing test for generated HLS project files**

Add a test that calls `materialize_hls_project(spec, out_dir, fpga_part)` and verifies:

- `kernel.cpp` contains real arithmetic loops tied to the spec kernel, not a constant scale stub.
- `tb.cpp` checks numeric golden outputs and prints `DSE_REAL_HLS_PASS` only after validation.
- `run_hls.tcl` runs `csim_design`, `csynth_design`, and attempts `cosim_design`.

- [ ] **Step 2: Run the failing test**

Run:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py::test_hls_project_materialization_contains_golden_correctness_and_cosim
```

Expected: FAIL because project generation is missing.

- [ ] **Step 3: Implement HLS project materialization**

Generate HLS C++ and testbench per architecture. Testbenches must compare expected numeric results with tolerances and include enough operations to derive latency from HLS reports. Tcl must attempt cosim after synthesis; if Vivado-HLS cosim fails because RTL simulator integration is unavailable, record that as a cosim blocker rather than claiming pass.

- [ ] **Step 4: Run the test**

Run the same pytest command. Expected: PASS.

### Task 3: Remote EDA Execution And Report Parsing

**Files:**
- Modify: `dse_v2/experiments/qe_ic_real_opportunity/real_hybrid_hls_evidence.py`
- Create: `dse_v2/scripts/dse/run_qe_ic_real_hybrid_hls_campaign.py`
- Test: `dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py`

- [ ] **Step 1: Write failing parser tests**

Add tests for `parse_vivado_hls_csynth_report()` using a small report fixture string with latency, interval, BRAM, DSP, FF, LUT and timing lines. Assert parsed numeric fields are returned and missing fields are marked with blockers.

- [ ] **Step 2: Run parser tests**

Run:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py -k parse_vivado
```

Expected: FAIL until parser exists.

- [ ] **Step 3: Implement remote runner and parser**

Implement a script that stages each HLS project to `/tmp/dse_real_hybrid_hls_*` on `ssh ic-eda`, runs `/home/Xilinx/Vivado/2019.1/bin/vivado_hls -f run_hls.tcl`, fetches stdout/stderr/csynth/cosim reports, parses latency/resource/Fmax, and writes `artifacts/qe_ic_real_hybrid_hls/<run_id>/real_hybrid_hls_evidence.json`.

- [ ] **Step 4: Run focused parser tests**

Run the parser tests. Expected: PASS.

### Task 4: Architecture Search Loop And Claim-Gated Comparison

**Files:**
- Modify: `dse_v2/experiments/qe_ic_real_opportunity/real_hybrid_hls_evidence.py`
- Modify: `dse_v2/scripts/dse/run_qe_ic_real_hybrid_hls_campaign.py`
- Test: `dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py`

- [ ] **Step 1: Write a failing comparison test**

Test that `classify_real_hybrid_vs_gpu()` does not conclude superiority from a single synthesis-only row; it must require measured GPU baseline, golden C-sim pass, HLS synthesis latency/resource, cosim/VCS pass or explicit blocker, full-SCF overhead accounting, and at least two attempted architecture families before returning a stronger/weaker conclusion.

- [ ] **Step 2: Run comparison test**

Run:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py -k classify_real_hybrid
```

Expected: FAIL until classifier exists.

- [ ] **Step 3: Implement claim-gated comparison**

Compare parsed HLS latency/resource against the measured GPU baseline records in `artifacts/qe_ic_7day_prelim/qe_ic_7day_gpu_baseline.json`. Convert kernel latency to workflow contribution only with explicit host/transfer/SCF overhead assumptions. If all tested real architectures are slower or blocked, return `fpga_hybrid_weaker` or `gpu_dominant` with evidence; if any passes conservative workflow speedup and gates, return `fpga_hybrid_stronger`; otherwise return `insufficient_evidence` with exact gaps.

- [ ] **Step 4: Run comparison tests**

Run the focused pytest. Expected: PASS.

### Task 5: Real Machine Campaign And Commit

**Files:**
- Artifact output: `artifacts/qe_ic_real_hybrid_hls/`
- Modify docs/report only if the run produces new evidence boundaries.

- [ ] **Step 1: Run local tests**

Run:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py dse_v2/tests/test_qe_ic_7day_prelim_runner.py
python3 -m compileall -q dse_v2
```

Expected: PASS.

- [ ] **Step 2: Run real remote HLS campaign**

Run:

```bash
python3 dse_v2/scripts/dse/run_qe_ic_real_hybrid_hls_campaign.py --gpu-baseline artifacts/qe_ic_7day_prelim/qe_ic_7day_gpu_baseline.json --out artifacts/qe_ic_real_hybrid_hls --max-architectures 3
```

Expected: HLS C-sim and C-synth attempted for multiple non-stub architectures; cosim/VCS attempted or exact blocker recorded; final JSON contains an evidence-backed preliminary label.

- [ ] **Step 3: Clean scratch**

Remove local `input_tmp.in`, HLS scratch directories not referenced by the report, Python caches, and QE wavefunction scratch. Preserve fetched stdout/stderr/report logs referenced by JSON hashes.

- [ ] **Step 4: Commit and push**

Run:

```bash
git status --short
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py dse_v2/tests/test_qe_ic_7day_prelim_runner.py
python3 -m compileall -q dse_v2
python3 -m json.tool artifacts/qe_ic_real_hybrid_hls/real_hybrid_hls_summary.json >/dev/null
git diff --check
git add dse_v2/experiments/qe_ic_real_opportunity/real_hybrid_hls_evidence.py dse_v2/scripts/dse/run_qe_ic_real_hybrid_hls_campaign.py dse_v2/tests/test_qe_ic_real_hybrid_hls_evidence.py artifacts/qe_ic_real_hybrid_hls docs/superpowers/plans/2026-06-08-real-hybrid-fpga-evidence-chain.md
git commit -m "feat: add real hybrid HLS evidence campaign"
git push origin feature/generic-dse-framework
```

Expected: branch contains real non-stub architecture evidence, not just generated stubs/proxies.
