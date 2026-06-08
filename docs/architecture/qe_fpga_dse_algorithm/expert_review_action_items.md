# Expert Review Action Items For QE Workflow-to-FPGA DSE

Status: consolidated after algorithm iterations 1-4.

## Overall Verdict

The work is directionally promising but not DAC-ready.  The current repository
contains a useful workflow-aware DSE scaffold, replayable reports, model-level
feedback, and package-generation plumbing.  It does not yet prove a strong
algorithmic or FPGA deployment result.

The strongest thesis is:

> Workflow abstractions predict fidelity-mismatch modes in scientific FPGA
> deployment and improve scarce high-fidelity promotion efficiency.

## DAC/EDA Reviewer

- **Verdict:** weak reject today.
- **Core objection:** Multi-fidelity active DSE is mainstream; the novelty must
  be workflow-mismatch-aware promotion.
- **Required actions:**
  - Make workflow-mismatch-aware promotion the main paper thesis.
  - Show workflow abstraction changes promotion decisions under independent
    fidelity.
  - Compare against random, NSGA-II/III, BO/EI, Hyperband, L1-only,
    kernel-only, and manual heuristics.
  - Report budget curves, rank inversion, promotion precision, top-k hit,
    regret, hypervolume, and calibration.

## Algorithm Reviewer

- **Verdict:** current implementation is deterministic ranking, not a serious
  learned/search algorithm yet.
- **Core objection:** no posterior, no genuine candidate proposal, no
  principled value-of-information.
- **Required actions:**
  - Add residual posterior/surrogate interface.
  - Add value-of-information for fidelity selection.
  - Add candidate neighborhood/proposal beyond finite-grid sorting.
  - Add search-quality metrics that are not exact selected-ID tests.

## QE/DFT Reviewer

- **Verdict:** partially correct but insufficient for whole-QE workflow DSE.
- **Core objection:** current abstraction is `pw.x`-centric and lacks broader QE
  semantics.
- **Required actions:**
  - Add richer stage classes: NSCF, relax/vc-relax, post-processing, restart,
    and optionally DFPT/phonon workflows for future scope.
  - Represent branch/merge, restart/reuse, convergence termination, and stage
    family data products.
  - Expand artifacts: occupations, projectors, force/stress trajectories,
    restart metadata, post-processing outputs, I/O volume by artifact.
  - Expand correctness observables beyond energy/residual/eigenvalues.
  - Ground claims in measured QE workflow bundles.

## FPGA/HLS Reviewer

- **Verdict:** credible scaffold, not deployment result.
- **Core objection:** generated HLS is a toy vector loop, not a QE kernel.
- **Required actions:**
  - Select one real QE-derived kernel path, preferably FFT/transpose or bounded
    `h_psi`.
  - Add kernel-specific implementation grammar: data layout, stream width,
    burst length, bank mapping, unroll, II target, array partitioning, DMA
    depth, clock, platform/part.
  - Generate candidate-specific pragmas, ports, HBM bindings, constraints, and
    report parsers.
  - Run HLS C-sim/C-synth and, when possible, Vivado implementation.
  - Keep host/control/transfer/sync costs in end-to-end accounting.

## Neural/Surrogate Reviewer

- **Verdict:** use neural networks as surrogate/ranker/uncertainty module only.
- **Core objection:** current neural backend is tabular and trained on L2 model
  labels; it cannot be the main contribution.
- **Required actions:**
  - Treat residual prediction over L1 as the target.
  - Prefer graph surrogate or graph transformer when enough data exists.
  - Use leave-workload-out and OOD validation.
  - Calibrate uncertainty with independent fidelity labels.

## Paper Reviewer

- **Verdict:** not submission-ready.
- **Core objection:** paper reads like artifact/provenance pipeline with a DSE
  method attached.
- **Required actions:**
  - Lead with the algorithmic thesis and hypotheses.
  - Move provenance details to appendix/supporting material.
  - Recast results around baselines, ablations, and promotion efficiency.
  - Keep limitations clear without making the paper read like a status report.

## Prioritized Next Implementation Tasks

1. **Measured full-QE workflow fixture**
   - Build one file-backed fixture that round-trips through
     `workflow_feature_contract` into Step2 search.
   - Include explicit stage DAGs, restart/reuse edges, artifact lifetimes,
     post-processing fan-out, and correctness observables.
   - Verdict: this is the next algorithm-enabling artifact; bitstream work is
     downstream.

2. **Executable algorithm contract**
   - Implement `p_m(x,w)` as a calibrated mispromotion model over measured
     workflow/candidate/mismatch features.
   - Implement `VOI_t(f | x,w)` with frontier information gain, calibration
     reuse, gate-resolution value, and prerequisite risk.
   - Keep deterministic WAMF as a baseline until posterior/VOI behavior exists.

3. **Sparse-label promotion benchmark**
   - Use fixed candidate pools and equal budgets across policies.
   - Sample promoted and non-promoted candidates for independent fidelity.
   - Report promotion precision, mispromotion rate, regret, top-k hit,
     constrained hypervolume, rank correlation, and bootstrap intervals.

4. **Workflow graph semantics**
   - Fix explicit-DAG branch semantics.
   - Fix stage-local compute weights.
   - Refine NSCF/relax repetition semantics.
   - Tests: focused workflow abstraction regressions.

5. **Mismatch-feature instrumentation**
   - Extract host-control, artifact lifetime, transfer/sync, post-processing,
     branch/reuse, resource-risk, and correctness-pressure features.
   - Include them in L1/L2/search reports.
   - Tests: feature values change under controlled fixtures.

6. **Search metrics**
   - Add promotion precision/recall and mispromotion rate to benchmark reports.
   - Add promoted/non-promoted sampling protocol.
   - Tests: synthetic benchmark where workflow features avoid rank inversion.

7. **Stronger algorithm loop**
   - Add posterior/surrogate interface for residual objectives and feasibility.
   - Add value-of-information fidelity selection.
   - Keep deterministic WAMF as baseline.

8. **Measured corpus path**
   - Write ingestion/runbook for file-backed measured QE bundles.
   - Define minimum corpus classes and metadata.
   - Add replay checks for measured inputs.

9. **Real implementation handoff**
   - Pick first QE-derived kernel path.
   - Add golden-vector manifest format.
   - Extend package grammar and generated HLS scripts.
   - Run available HLS/Vivado gates without upgrading unsupported evidence.
