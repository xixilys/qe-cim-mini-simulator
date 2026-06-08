# Expert Review Notes

Date: 2026-06-01

Scope: multi-perspective review of the current QE-to-FPGA DSE prototype and ACM/DAC manuscript scaffold.

## Verdict

The current state is a useful research scaffold and a compilable ACM/DAC-style manuscript package. It is not yet a complete DAC-grade hardware-result paper. The strongest current contribution is workflow-aware DSE artifact generation, an initial adaptive multi-fidelity search report, and promotion-to-package plumbing. The missing core is independent evidence: real QE profiles, independent high-fidelity models, real kernel correctness, and HLS/Vivado/bitstream closure.

## Multi-Agent Review, 2026-06-01

- Algorithm reviewer verdict: weak reject as a DAC algorithm paper today. The search framing matches mainstream analytical/surrogate/multi-fidelity DSE practice, but the current comparison is still dominated by a related Python L2 model family. Required fixes are independent-fidelity budget curves, rank correlation across L1/L2/generic-sim/gem5/SystemC/HLS/Vivado samples, stronger baselines, and workflow ablations that actually move rankings.
- Hardware reviewer verdict: defensible only as methods/scaffold work, not as QE/DFT FPGA acceleration evidence. The missing gates are real QE-derived correctness vectors, HLS C-sim/C-synth or RTL simulation/synthesis, constrained Vivado implementation/timing/utilization/power, bitstream or xclbin generation, and end-to-end full-SCF host/device timing and energy with transfers and synchronization included.
- Manuscript and reproducibility reviewer verdict: not submission-ready. The table-generation path needed source provenance, reader-facing labels, non-empty workload metadata, clearer generic-sim wording, and regeneration commands. The remaining submission blockers are real QE measured corpus provenance, artifact hashes tied to paper tables, cleaner bibliography/template warnings, and avoiding any wording that presents fixture/model evidence as a hardware result.
- Cross-review conclusion: do not submit as a completed DAC paper without the real QE measured corpus, independent high-fidelity calibration, kernel correctness, and HLS/Vivado/bitstream evidence. The current manuscript can be a rigorously labeled methodology scaffold only.

## Algorithm and DSE Review

- The main model constants are hand-authored. The current result demonstrates a structured heuristic, not yet a validated search algorithm.
- L1, L2, baselines, calibration, and multi-workload results share the same Python model family, so the current search comparison is partly circular.
- The current prototype now has an early adaptive report with online residual-surrogate updates, acquisition components, and budget-limited lazy L2 observations. Full-oracle rank/regret is intentionally kept in separate retrospective baseline artifacts, but the feedback source is still L2 Python TLM rather than independent SystemC/gem5/HLS/Vivado evidence.
- Update 2026-06-01: external feedback validation now includes a policy-level comparison section. When L3/SystemC, HLS, or other independent feedback samples are supplied, the report computes per-policy feedback overlap, best feedback EDP, feedback rank, and top-k hit for the candidates selected by each search policy. This is the right structure for DAC experiments, but sparse or synthetic feedback samples still do not prove method superiority.
- Update 2026-06-01: promoted QE FPGA L2 request bundles can now be translated into `gsim.request.v1` and executed with the standalone `generic_sim` backend through `run_qe_fpga_l3_generic_sim_feedback.py`. The runner emits per-candidate generic-sim requests/results plus `feedback_samples.json` that can be fed back into the DSE policy-validation path. This is executable L3 timing/projection feedback, not QE physics correctness, HLS/Vivado, or bitstream evidence.
- Baselines need equal-budget repeated runs and stronger competitors: random with many seeds, NSGA-II/III, Bayesian optimization or surrogate search, Hyperband/successive halving, single-fidelity L1, kernel-only, and manual heuristics.
- Required metrics beyond the current model-level report: best-found-vs-budget on independent fidelity, oracle regret against non-Python-model evidence, top-k hit rate, rank correlation across fidelities, promotion precision/recall, sensitivity to model noise, and runtime overhead.

## QE Workload Review

- Current QE workloads are fixture-level and too small to represent QE deployment decisions.
- Update 2026-06-01: the workflow abstraction now accepts QE-native file-path bundles for `pw.x` input, stdout/profile logs, `prefix.save/`-style artifact directories, and pseudopotential paths. It records QE version, MPI/OpenMP counts, observed energy/residual/Fermi observables, save-dir file refs/sizes, UPF hashes, and explicit `qe_save_dir` stage-artifact dependency edges. This reduces the input-abstraction gap but is still parser coverage, not a measured workload corpus.
- Update 2026-06-01: the deployment CLI now resolves `--workflow-bundle` relative paths against the bundle directory and records nested input refs for QE input/log/profile files, save-dir directories, and pseudopotentials in the replay manifest and summary. This makes file-backed QE workflow bundles replayable at the artifact-binding level.
- Update 2026-06-01: the deployment CLI now accepts a `--workflow-corpus` JSON containing multiple QE workflow bundles. It emits `qe_fpga_workload_corpus_report.json` with workload count, class coverage, dimension ranges, observed-runtime coverage, nested artifact refs, and corpus-level provenance. This is the right input shape for future multi-workload experiments, but it still does not prove representativeness unless the corpus is curated from real QE runs.
- Update 2026-06-01: the replay verifier now checks external workflow-bundle input refs, including nested QE input/log/profile files, pseudopotential files, and save-dir directory contents. Mutating a referenced QE input after the manifest is created is reported as a mismatched input ref, not merely ignored as out-of-run state.
- Remaining QE-state gap: real multi-program QE suites still need broader parser coverage for XML metadata, eigenvalues, occupations, UPF metadata semantics, nonlocal projector data, restart behavior, and I/O volumes across representative materials and sizes.
- SCF dynamics are under-modeled: iteration count, mixing trajectory, diagonalization inner loops, FFT/rho/veff updates, convergence behavior, MPI/OpenMP decomposition, and synchronization barriers.
- Required measured inputs: real QE input decks, UPF hashes, QE version/build flags, CPU hardware, MPI/OpenMP layout, stdout timers, parsed per-stage/per-kernel timing, FFT grid, `npw/npwx/ngm/nrxx/nbnd/nks`, file sizes, and SCF convergence traces.
- The evaluation must include negative cases where h_psi acceleration is not enough because diagonalization, FFT transpose, I/O, mixing, post-processing, or synchronization dominates.

## FPGA/HLS/EDA Review

- Generated HLS is currently a candidate-bound scaffold, not a real QE accelerator.
- No golden correctness vectors exist for FFT, projector, h_psi, reductions, density update, or workflow-level invariants.
- Passing HLS on the current vector loop would not demonstrate QE acceleration.
- Required package content: real kernel source, testbench, tolerance policy, generated dimensions from QE inputs/logs, memory map, AXI/HBM bank mapping, part/platform constraints, HLS/Vivado scripts, report parsers, and host invocation path.
- Reportable FPGA evidence requires HLS C-sim or RTL sim, HLS/RTL synthesis, Vivado synthesis, Vivado implementation/timing closure, utilization/timing/power report parsing, artifact hashes, and bitstream/xclbin manifest when platform constraints exist.
- The new generic-sim feedback runner closes only a standalone L3 timing/projection path. It does not replace HLS C-sim/C-synth, Vivado implementation, board execution, bitstream generation, or QE numerical correctness gates.

## Paper Review

- The paper should frame the current state as workflow-aware multi-fidelity DSE for QE-targeted FPGA acceleration planning, not as completed QE acceleration.
- Avoid implying hardware speedup until independent SystemC/gem5/HLS/Vivado/board evidence exists.
- The manuscript needs figures/tables for the method pipeline, QE workflow DAG, candidate-space dimensions, workload suite, baselines, budget-vs-result curves, rank correlation, Pareto plots, ablations, and HLS/Vivado PPA.
- Related work positioning must be sharper against HLS DSE, surrogate-assisted DSE, analytical mapper DSE, and workflow-level scientific-computing acceleration.
- Main reviewer objections to preempt: model evaluates itself; generated HLS is unrelated to QE; no real FPGA implementation; synthetic workloads are not application evidence; baselines are weak; full-SCF costs are not measured.

## Artifact and Reproducibility Review

- The run summary and replay manifest now record argv, environment, input refs, payload hashes, and byte hashes for generated JSON artifacts.
- Update 2026-06-01: corpus-mode replay manifests bind the corpus JSON, each workload bundle, and nested QE input/log/profile/save-dir/pseudopotential refs. Mutating a corpus workload input after the run is caught as a mismatched corpus nested input ref.
- Update 2026-06-01: the replay verifier now performs lightweight semantic contract validation for generated JSON artifacts and rejects a rehashed artifact when required fields such as the workload graph are removed. This closes the simplest "tamper and rehash" hole for known artifacts.
- Update 2026-06-01: feedback validation reports now require the policy-validation section in replay semantic checks, so deleting the independent-feedback policy comparison while rehashing the artifact is treated as a contract error.
- Needed provenance beyond current hashing and lightweight contracts: package versions, command transcript, tool availability, raw log references, experiment re-execution from inputs, full JSON Schema files, registry entries, and migration rules.
- Schema strings and lightweight contracts exist, but there are still no full JSON Schema files, schema registry entries, or migration rules.
- Current tests now cover basic replay checks and simple tamper/rehash rejection, but they still do not validate independent ranking quality or measured hardware evidence.
- The fake HLS test checks command plumbing only. It must not be used as hardware evidence.

## Next Experiments Required

1. Real QE workload ingestion and profiling across representative materials and sizes.
2. Full workflow feature extraction from QE inputs/outputs/logs instead of synthetic fixture scaling.
3. Independent L3/L4 evidence for promoted and non-promoted samples.
4. Golden correctness vectors for major accelerated kernels and workflow outputs.
5. Real HLS/Vivado closure for at least one representative kernel path.
6. Equal-budget search comparison with repeated seeds, stronger baselines, and ablations.
7. Calibration and robustness analysis across model noise and fidelity levels.
8. Replay manifest and schema validation for all emitted artifacts.
