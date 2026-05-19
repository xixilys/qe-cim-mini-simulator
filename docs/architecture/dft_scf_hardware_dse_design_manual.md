# DFT/QE Full-SCF Hardware DSE Design Manual

**Status:** design manual seed / not execution-complete  
**Primary source:** `docs/dse_instruction.md`  
**Planning artifact:** `.omx/plans/dft-scf-hardware-dse-codesign-master-plan-20260519T062553Z.md`

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

The frozen suite must cover six SCF classes:

1. small multi-k;
2. metal/smearing;
3. insulator;
4. slab/vacuum large FFT;
5. gamma-only supercell;
6. projector/orthogonalization-heavy.

## 3. Candidate space

Use multiple hardware template families:

- streaming FFT-Hψ;
- projector-heavy;
- memory/HBM-rich;
- hybrid CPU-FPGA;
- ASIC tile/template.

Candidate bounds are two-tier:

- `release_tier`: conservative, synthesizable, eligible for formal Pareto only after evidence gates;
- `exploratory_tier`: wider search, isolated from trusted claims until promoted;
- `seed_source`: literature or existing FPGA-HBM/FFT/NoC/HLS designs should seed initial ranges where possible.

## 4. Search policy

The first search path is **hierarchical funnel search**:

1. template-family enumeration and legality checks;
2. analytic SCF cost-model rough screening;
3. bottleneck-guided local refinement;
4. small HLS/RTL/PPA calibration batch;
5. Pareto/frontier reporting only for evidence-eligible candidates.

Later NSGA-II, BO/EHVI, ensemble, or MCTS search can be added as plugins, but they must use the same candidate-tier and evidence contracts.

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

## 6. First prototype boundary

The first prototype is **full-SCF evaluated hybrid**:

- hardware claims: FFT/transpose/Hψ/projector/reduction/DMA only when gates pass;
- CPU keeps: I/O, input parsing, SCF control, convergence checks, diagonalization, mixing;
- mandatory cost accounting: host-bound compute, synchronization, host-device transfer, queueing, launch overhead, and layout conversion outside accelerated paths.

Do not report full-SCF speedup by hiding host-bound or transfer costs. Report kernel-level speedups separately from end-to-end SCF evaluated speedup.

## 7. Completion discipline

Completion requires strict workload bundles, realistic candidate generation, claim-specific evidence gates, full-SCF evaluated reporting, and docs kept synchronized with code/schema/evidence changes. Intermediate green tests or runnable demos are progress only unless every final gate is satisfied.

## 8. RALPLAN workstream governance addendum

The approved follow-up plan adds an integration-governance lane before broad implementation.

### Lane J — Integration Spine & Contract Governance

Lane J owns the canonical schema/ID/contracts that allow workload, search, tool, evidence, report, and documentation lanes to compose:

- artifact/schema registry and versioning;
- strict bundle contract;
- candidate/tier contract;
- evidence/adjudication/report handoff contract;
- `campaign_id`, `workload_run_id`, `trial_id` propagation;
- release/exploratory isolation;
- migration/deprecation policy;
- cross-lane compatibility tests.

### Wave 1.5 thin trace

Before broad HLS/RTL/tool/kernel work scales out, the system must run a progress-only thin trace:

```text
strict workload bundle
→ release-tier DMA/HBM or transpose candidate
→ tool transcript or blocker
→ Step4 adjudication
→ Step5 report
```

This trace validates the integration spine only. It must not be reported as final completion.

### Reporting invariants

Step5 must report kernel speedup separately from end-to-end SCF evaluated speedup and include host-bound, transfer, synchronization, queueing, and layout costs.  Formal Pareto/frontier excludes exploratory, model-only, blocked, fake-PPA, and wrong-claim-type candidates.
