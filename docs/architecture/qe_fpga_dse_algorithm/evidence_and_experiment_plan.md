# QE Workflow-to-FPGA DSE Evidence And Experiment Plan

Status: evidence plan after `alg-iter-002`.

This plan defines the evidence needed to show that WAMF-DSE is feasible and
algorithmically useful.  It is not a hardware-claim checklist.  Its purpose is
to prove or falsify the research hypothesis:

> Workflow-mismatch-aware promotion improves scarce high-fidelity evaluation
> efficiency for QE-to-FPGA deployment DSE.

## Evidence Levels

| Level | Evidence | Use In Paper |
| --- | --- | --- |
| `E0` repository contract/tests | Guards method semantics and replayability | implementation confidence only |
| `E1` synthetic independent mismatch benchmark | Early algorithm stress test | method development, not final proof |
| `E2` file-backed measured QE workflow corpus | Workload realism | workload validity |
| `E3` independent L3/SystemC/gem5/generic-sim samples | Calibration and rank-inversion evidence | algorithm evidence |
| `E4` HLS C-sim/C-synth or RTL sim/synth | implementation feasibility | kernel/tool evidence |
| `E5` Vivado implementation/bitstream/board | FPGA deployment evidence | final hardware claim only |

## Workflow-Mismatch Feature Matrix

| Feature | Source | Cheap-Model Failure Mode | Ablation |
| --- | --- | --- | --- |
| host-control pressure | SCF/relax loops, convergence, mixing, diagonalization, barriers | Offloading compute-heavy kernels looks too good while host orchestration dominates | remove host-control/sync |
| artifact lifetime pressure | `prefix.save`, wavefunctions, charge density, eigenvalues, restart metadata | Candidate ignores reuse/checkpoint cost or overcounts persistent residency benefit | remove data-object lifetime |
| transfer/sync pressure | file sizes, HBM/DDR movement, DMA windows, stage dependencies | Streaming candidate wins L1 but loses when transfers serialize workflow | remove transfer/sync |
| post-processing fan-out | bands/DOS/projwfc/DFPT consumers | Kernel-only search underweights data reuse and output fan-out | remove post-processing stages |
| branch/restart/reuse sensitivity | explicit DAG branches, restart chains, stage artifacts | Linear stage model promotes wrong schedule or residency plan | remove workflow DAG, use stage order |
| resource-cliff risk | lanes, banks, tile size, HLS/Vivado resource estimates | Candidate with better L1 performance fails timing/resource at higher fidelity | remove implementation feasibility |
| correctness pressure | observables, tolerances, golden vectors | Mixed precision or approximate mapping appears feasible but is not valid | remove correctness pressure |

## Baselines

Minimum equal-budget baselines:

- seeded random over legal candidates;
- manual HBM streaming heuristic;
- L1-only EDP ranking;
- kernel-hotspot-only ranking;
- SCF-only or single-stage abstraction;
- NSGA-II/III over L1 objectives;
- BO/EI or surrogate expected improvement over candidate vectors;
- Hyperband/successive halving with fidelity ladder;
- no-workflow-abstraction WAMF ablation;
- no-multi-fidelity-calibration WAMF ablation;
- no-uncertainty WAMF ablation;
- no-implementation-risk WAMF ablation.

## Metrics

Search quality:

- best-found objective versus budget;
- simple regret against independent-fidelity oracle subset;
- constrained hypervolume and hypervolume ratio;
- top-k hit rate;
- promotion precision and recall;
- mispromotion rate;
- rank correlation across fidelity pairs;
- time and tool-cost normalized improvement.

Model quality:

- residual RMSE by workflow class;
- calibration error and interval coverage;
- feasibility calibration;
- OOD workload holdout performance;
- uncertainty-quality correlation with observed residual error.

Deployment feasibility:

- HLS C-sim pass/fail;
- HLS C-synth latency/resource;
- Vivado timing/utilization/power;
- host-transfer/sync accounting;
- final blocker distribution.

## Required Ablation Table

| Ablation | Removed Component | Expected Failure If Method Is Correct |
| --- | --- | --- |
| no-workflow-DAG | branch/reuse/control edges | rank inversions on branched or reuse-heavy workflows |
| kernel-histogram-only | stage/data/control structure | over-promotes compute-hot candidates with bad transfers |
| no-host-control | convergence/mixing/diagonalization barriers | overestimates device-resident speedup |
| no-data-lifetime | artifact persistence/residency | misses HBM/checkpoint reuse decisions |
| no-multi-fidelity | calibration/update loop | poor sample efficiency under mismatch |
| no-uncertainty | exploration term | fails to discover candidates outside L1 prior |
| no-implementation-risk | resource/timing feasibility | promotes candidates that fail HLS/Vivado |

## Minimal Viable Evidence Path

The smallest credible algorithm paper path is:

1. Build a measured QE workflow corpus with at least:
   - SCF + NSCF + bands/DOS;
   - relax or vc-relax;
   - a data-heavy workflow;
   - a host-control-heavy workflow;
   - a post-processing fan-out workflow.
2. Run L1/L2 search over all legal candidates or a large legal subset.
3. Select promoted and deliberately non-promoted samples for independent L3 or
   generic-sim/SystemC-style feedback.
4. Show rank inversions where L1/kernel-only/SCF-only are wrong and WAMF-DSE is
   less wrong.
5. Run at least one real HLS C-sim/C-synth path for a QE-derived kernel package.
6. Feed the independent results back into calibration and show improved next
   promotion decisions.

This path still does not prove final FPGA speedup.  It can prove method
feasibility and algorithmic usefulness.

## Sparse-Label Promotion Protocol

High-fidelity labels will be scarce, so the experiment must be paired and
budget-controlled instead of winner-only.

Minimum protocol:

- build a fixed legal candidate pool per workflow fixture;
- run every policy on the same pool and with the same high-fidelity budget;
- use budget checkpoints such as `2`, `4`, `8`, and `16` observations per
  workflow class when resources allow;
- sample both promoted candidates and deliberately non-promoted candidates for
  independent fidelity so promotion precision and recall are estimable;
- stratify samples by workflow-mismatch class: host-control-heavy,
  transfer-heavy, artifact-reuse-heavy, post-processing-fanout, and
  resource-risk-heavy;
- compute bootstrap confidence intervals for regret, top-k hit, hypervolume,
  promotion precision, and mispromotion rate;
- use leave-workload-out validation for any learned residual, feasibility, or
  mispromotion model;
- keep candidate generation fixed across ablations when testing whether
  workflow features matter.

The key falsification test is:

```text
If workflow-mismatch features are removed while the candidate pool and budget
remain fixed, the policy should promote more candidates that are not useful
under independent fidelity on mismatch-heavy workflow classes.
```

If this does not happen, the central WAMF-DSE thesis is unproven or wrong.

## Expert Review Gates

| Reviewer | Must Accept |
| --- | --- |
| DAC/EDA | Thesis is not generic multi-fidelity search; evidence shows workflow abstraction changes promotion. |
| Architecture | Candidate grammar represents real FPGA deployment choices and resource constraints. |
| FPGA/HLS | At least one generated package binds real kernel semantics to tool scripts and reports. |
| QE/DFT | Workload corpus and observables are representative enough for stated scope. |
| Algorithms | Baselines, ablations, metrics, and budget protocol are fair and non-circular. |
| Industry | Method reduces expensive validation effort and produces actionable implementation candidates. |

## Immediate Implementation Task Map

1. Build a measured full-QE workflow fixture:
   - round-trip QE-like input, logs, profiles, artifacts, and correctness
     observables into `workflow_feature_contract`;
   - include SCF, NSCF, post-processing fan-out, relax or vc-relax,
     restart/reuse, and artifact lifetimes;
   - feed the fixture into Step2 search problem construction.
2. Fix workflow graph semantics:
   - stop serializing independent branches when explicit dependencies exist;
   - make stage-local compute weights independent from global aggregate weights;
   - refine NSCF/relax repetition semantics.
3. Strengthen workflow contract:
   - add restart/reuse edges and artifact versions;
   - add richer QE stage classes and correctness observables;
   - bind measured bundle metadata.
4. Strengthen deployment grammar:
   - add implementation-level knobs for one real kernel path;
   - bind memory banking, stream width, unroll, II, DMA depth, platform/part.
5. Strengthen search algorithm:
   - add mismatch-feature extraction;
   - add posterior/residual model interface;
   - add VOI-based fidelity choice;
   - add promotion precision and mispromotion metrics.
6. Strengthen evidence:
   - create promoted and non-promoted independent feedback sampling plan;
   - add baseline/ablation reports with equal-budget curves;
   - add at least one real HLS C-sim/C-synth evidence path.
