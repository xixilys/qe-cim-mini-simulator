# GPU QE And EDA Stub Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Locate or build GPU-enabled QE, report exact GPU-QE blockers, and always generate Layer-4 EDA stub evidence for the three selected candidates.

**Architecture:** QE capability detection stays in the environment/gpu-baseline boundary and requires both executable probing and dynamic-library evidence. EDA stub evidence is a separate non-claimable artifact that records generated HDL plus real remote tool execution without pretending to be workflow high-fidelity runtime evidence.

**Tech Stack:** Python 3, pytest, Quantum ESPRESSO executables, SSH-controlled `ic-eda`, VCS/Vivado/DC, JSON artifacts.

---

### Task 1: QE GPU Capability And Final Answer

**Files:**
- Modify: `dse_v2/experiments/qe_ic_real_opportunity/environment_probe.py`
- Modify: `dse_v2/experiments/qe_ic_real_opportunity/opportunity_campaign.py`
- Modify: `dse_v2/experiments/qe_ic_real_opportunity/schema.py`
- Test: `dse_v2/tests/test_qe_ic_real_opportunity_campaign.py`

- [ ] **Step 1: Write failing tests**

Add tests that simulate CPU-only QE and build failure:

```python
def test_execute_real_cpu_only_qe_uses_precise_final_answer(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(
        CONFIG_PATH,
        out_dir=tmp_path,
        execute_real=True,
        allow_generated_inputs=True,
        nonblocking=True,
    )
    assert report["final_answer"]["overall_answer"] == "gpu_qe_binary_cpu_only"
    assert "gpu_qe_binary_cpu_only" in report["final_answer"]["missing_evidence"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_opportunity_campaign.py::test_execute_real_cpu_only_qe_uses_precise_final_answer
```

Expected: FAIL because current code reports `gpu_or_eda_failure`.

- [ ] **Step 3: Implement minimal behavior**

Use GPU baseline blockers to map final answers:

```python
if baseline has gpu_qe_binary_cpu_only:
    overall_answer = "gpu_qe_binary_cpu_only"
elif baseline has gpu_qe_build_failed:
    overall_answer = "gpu_qe_build_failed"
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_opportunity_campaign.py -k 'gpu_qe'
```

Expected: PASS.

### Task 2: Candidate Stub Generation And EDA Evidence

**Files:**
- Create: `dse_v2/experiments/qe_ic_real_opportunity/eda_stub_evidence.py`
- Modify: `dse_v2/experiments/qe_ic_real_opportunity/opportunity_campaign.py`
- Modify: `dse_v2/experiments/qe_ic_real_opportunity/validation.py`
- Test: `dse_v2/tests/test_qe_ic_real_opportunity_campaign.py`

- [ ] **Step 1: Write failing tests**

Add tests for non-claimable stub artifact generation and campaign continuation:

```python
def test_generated_eda_stub_evidence_covers_three_selected_candidates(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(
        CONFIG_PATH,
        out_dir=tmp_path,
        execute_real=True,
        allow_generated_inputs=True,
        nonblocking=True,
    )
    artifact = _load_json(Path(report["real_run_artifacts"]["candidate_eda_stub_evidence_real_run"]))
    assert len(artifact["candidate_stub_results"]) == 3
    assert artifact["claim_strength"] == "none"
    assert "blocked_by_missing_candidate_design" not in report["environment_summary"]["blockers"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_opportunity_campaign.py::test_generated_eda_stub_evidence_covers_three_selected_candidates
```

Expected: FAIL because no stub artifact exists and design blocker is still added.

- [ ] **Step 3: Implement generator and runner**

Generate one SystemVerilog stub per selected candidate, create a VCS/Vivado/DC script, run the first available remote tool through `ssh ic-eda` with `LC_ALL=C LANG=C`, and emit:

```json
{
  "schema_version": "dse.qe_ic.eda_stub_evidence.v1",
  "results_are_real": false,
  "claim_strength": "none",
  "candidate_stub_results": []
}
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_opportunity_campaign.py -k 'eda_stub or candidate_design'
```

Expected: PASS.

### Task 3: Real Machine Verification

**Files:**
- Modify: `docs/architecture/qe_ic_real_opportunity_campaign_v1.md`
- Update generated artifacts under `artifacts/qe_ic_real_opportunity_campaign_real_run/`

- [ ] **Step 1: Run target tests**

Run:

```bash
python3 -m pytest -q dse_v2/tests/test_qe_ic_real_opportunity_campaign.py
```

Expected: PASS.

- [ ] **Step 2: Compile imports**

Run:

```bash
python3 -m compileall dse_v2/experiments/qe_ic_real_opportunity dse_v2/scripts/dse/run_qe_ic_real_opportunity_campaign.py
```

Expected: PASS.

- [ ] **Step 3: Run real nonblocking campaign**

Run:

```bash
python3 dse_v2/scripts/dse/run_qe_ic_real_opportunity_campaign.py --config dse_v2/testdata/qe_ic_real_opportunity/qe_ic_real_opportunity_campaign_config_template.json --out artifacts/qe_ic_real_opportunity_campaign_real_run --execute-real --allow-generated-inputs --nonblocking
```

Expected: PASS, final answer is `gpu_qe_binary_cpu_only` on the current machine unless a GPU-enabled QE is found, and EDA stub evidence artifact exists.
