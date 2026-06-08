# QE Workflow-to-FPGA DSE Algorithm Iteration Ledger

This ledger records algorithm-design iterations for the QE Workflow-to-FPGA
DSE method.  It is intentionally separate from evidence ledgers: the purpose is
to preserve how the method evolves, why changes were accepted or rejected, and
what evidence is still required before any DAC-level claim is defensible.

## Iteration 1 - From WAMF Scaffold To Workflow-Mismatch-Driven DSE

- **iteration_id:** `alg-iter-001`
- **timestamp:** `2026-06-02 18:07:17 +0800`
- **starting hypothesis:** A workflow-abstraction-guided multi-fidelity active
  search method can be the center of a DAC-grade QE-to-FPGA DSE paper if it is
  framed as a complete workflow-to-deployment co-design system rather than as a
  standalone acquisition function.
- **design question being tested:** Is the current WAMF-DSE direction a complete
  and differentiated algorithmic contribution, or is it only a deterministic
  search-control scaffold around existing DSE ingredients?
- **sources/code/paper sections inspected:**
  - `dse_v2/reference_workloads/qe_workflow_fpga_abstraction.py`
  - `dse_v2/reference_workloads/qe_fpga_deployment_dse.py`
  - `dse_v2/reference_workloads/qe_mainflow.py`
  - `dse_v2/mapping/search_policy.py`
  - `dse_v2/mapping/multifidelity_active_search.py`
  - `dse_v2/mapping/multifidelity_benchmark.py`
  - `dse_v2/tests/test_qe_workflow_fpga_abstraction.py`
  - `dse_v2/tests/test_qe_fpga_deployment_dse.py`
  - `dse_v2/tests/test_multifidelity_active_search.py`
  - `dse_v2/tests/test_multifidelity_benchmark.py`
  - `paper/dac_qe_fpga_dse/main.tex`
  - `paper/dac_qe_fpga_dse/expert_review_notes.md`
  - Mainstream DSE framing from MAESTRO, ZigZag, Timeloop, NSGA-II, BO/HLS
    tuning, and multi-fidelity/surrogate-assisted DSE practice.
- **algorithm changes proposed:**
  1. Reframe the method around the thesis
     `workflow abstractions predict fidelity-mismatch modes and improve scarce
     high-fidelity promotion efficiency`, not around a generic EHVI-like
     acquisition function.
  2. Replace the "single acquisition kernel is the method" framing with a
     four-layer method:
     workflow abstraction, deployment grammar, multi-fidelity probabilistic
     model, and candidate/fidelity action selection with implementation handoff.
  3. Treat current WAMF scoring as a deterministic baseline/scaffold, not as the
     final algorithm.
  4. Upgrade the planned search algorithm toward a hierarchical multi-fidelity
     BO/bandit method with learned objective/feasibility posteriors and
     explicit value-of-information for the next fidelity.
  5. Make workflow features affect concrete decisions: legality filtering,
     candidate generation, offload boundary construction, promotion priority,
     fidelity choice, and calibration grouping.
  6. Require experiments that show workflow abstraction prevents mispromotion
     under independent high-fidelity feedback.
- **expert-agent critiques received:**
  - **Algorithm/DSE reviewer:** Current policy is deterministic ranking over
    enumerated candidates; it lacks a probabilistic surrogate, posterior,
    genuine candidate proposal, principled fidelity allocation, and sample
    efficiency evaluation.
  - **Neural/surrogate reviewer:** Neural components fit only as residual
    surrogate/ranker/uncertainty modules.  Current implementation is tabular,
    label-starved, and trained on L2 model labels, not independent hardware/QE
    evidence.
  - **QE workflow reviewer:** The abstraction is not SCF-only anymore, but it is
    still mostly `pw.x`-centric and scalarized.  It lacks broader QE stages,
    real branch/restart/reuse semantics, rich artifacts, and measured corpus
    grounding.
  - **DAC/EDA reviewer:** Weak reject today.  The publishable angle is not
    "multi-fidelity active DSE" but workflow-abstraction-guided promotion for
    scientific accelerator deployment.
  - **FPGA/HLS reviewer:** Deployment grammar and handoff are fail-closed
    scaffolds.  Real kernel implementations, package-level FPGA knobs, golden
    vectors, HLS C-sim/C-synth, Vivado implementation, and host-inclusive
    accounting are required.
  - **Paper reviewer:** The manuscript is artifact/provenance-heavy and does
    not yet isolate one crisp algorithmic thesis.
- **accepted changes:**
  - Accept the DAC/EDA thesis shift: the core contribution is workflow-mismatch
    aware promotion, not another weighted EHVI controller.
  - Accept that current WAMF scoring is not enough for a serious algorithm
    claim; it becomes the initial scaffold and one baseline.
  - Accept the need for a graph/workflow contract that drives search decisions,
    not merely report labels.
  - Accept residual surrogate modeling over L1 predictions as the right neural
    role, while requiring calibrated uncertainty and independent labels.
  - Accept that implementation handoff must influence the grammar and fidelity
    ladder; generated toy HLS cannot support deployment claims.
- **rejected changes and reason:**
  - Reject making a neural network the main contribution.  Data scale and
    independent labels are insufficient; neural models are supporting
    surrogates.
  - Reject keeping SCF-only measured seeds as a completion path.  They may be
    calibration seeds but cannot prove whole-QE workflow DSE.
  - Reject treating evidence matrices as the search process.  Evidence is a
    promotion, calibration, and adjudication service.
  - Reject claiming DAC readiness from current model-level artifacts.
- **unresolved risks:**
  - Workflow abstraction is still too shallow for a strong whole-QE claim.
  - Current search space is enumerable and heuristic; scalability and candidate
    proposal are unproven.
  - Current feedback remains L1/L2/model-family dominated.
  - FPGA package generation does not yet bind real QE kernels or platform
    constraints.
  - The paper may still look like a careful scaffold unless results prove that
    workflow features change expensive-promotion decisions.
- **evidence needed next:**
  - Real or at least file-backed measured QE workflow corpus with stage timers,
    dimensions, artifacts, and host-control traces.
  - Independent-fidelity samples, starting with generic-sim/SystemC-like runs
    and then HLS/Vivado samples for promoted and non-promoted candidates.
  - Equal-budget search curves versus random, NSGA-II/III, BO/EI,
    Hyperband/successive halving, L1-only, kernel-only, and manual HBM
    heuristics.
  - Ablations removing workflow DAG, data lifetime, host-control/sync,
    multi-fidelity calibration, uncertainty, and implementation feasibility.
  - Mispromotion analysis showing when kernel-only or scalar workflow models
    select candidates that fail under higher fidelity.
- **current method version summary:** `WAMF-DSE v0.2` is a workflow-mismatch
  aware multi-fidelity co-design method in design form.  It consists of:
  graph-based QE workflow abstraction, deployment grammar, multi-fidelity
  residual surrogate, candidate/fidelity action policy, and implementation
  handoff.  The current repository implements parts of this, but the algorithm
  evidence is not yet strong enough for DAC claims.
- **progress delta:** The method evolved from "workflow-aware EHVI-like
  selection" to "workflow-mismatch-driven promotion and calibration for
  scientific FPGA deployment."
- **technical verdict:** Stronger, but incomplete.  The new framing is more
  defensible and more distinct from generic BO/NSGA-II/HLS tuning, but the
  required abstraction and independent evidence are not yet present.
- **next-iteration objective:** Formalize `WAMF-DSE v0.3` with explicit state,
  action, posterior/update, value-of-information, workflow-mismatch model,
  deployment grammar, and evaluation protocol; then identify the minimal code
  changes needed to make the repository's artifacts match that method.

## Iteration 2 - Formalizing Workflow-Mismatch-Aware Promotion

- **iteration_id:** `alg-iter-002`
- **timestamp:** `2026-06-02 18:07:17 +0800`
- **starting hypothesis:** The method becomes more DAC-defensible if workflow
  abstraction is used to predict when cheap models will mis-rank FPGA deployment
  candidates, then uses that prediction to allocate scarce higher-fidelity
  evaluations.
- **design question being tested:** Can "workflow awareness" be stated as a
  measurable algorithmic signal instead of an annotation or provenance label?
- **sources/code/paper sections inspected:**
  - `docs/architecture/qe_fpga_dse_algorithm/method_design_v0.md`
  - `paper/dac_qe_fpga_dse/main.tex`
  - `paper/dac_qe_fpga_dse/expert_review_notes.md`
  - `dse_v2/mapping/multifidelity_benchmark.py`
  - `dse_v2/reference_workloads/qe_mainflow.py`
  - Expert reviews from DAC/EDA, algorithm, neural surrogate, QE/DFT,
    FPGA/HLS, and paper-review perspectives.
- **algorithm changes proposed:**
  1. Define a workflow-mismatch vector `phi_m(G_w, x)` for each workflow graph
     and candidate, covering host-control pressure, artifact lifetime pressure,
     transfer/synchronization pressure, post-processing fan-out, restart/reuse
     sensitivity, resource-cliff risk, and implementation handoff risk.
  2. Replace a fixed workflow-risk score with a learned or calibrated
     mismatch model:
     `Pr[rank_L1(x) is misleading | phi_m(G_w, x), phi_x]`.
  3. Split acquisition into two explicit terms:
     Pareto improvement and mispromotion-avoidance value.
  4. Make the fidelity action value depend on expected calibration reuse for
     candidate neighborhoods, not only on hand-authored fidelity metadata.
  5. Define the key experiment as promotion precision: among candidates promoted
     by each policy under the same budget, how many remain Pareto-useful or
     implementation-feasible under independent fidelity?
- **expert-agent critiques received:**
  - **DAC/EDA:** The publishable thesis must show workflow abstraction changes
    promotion decisions under independent fidelity.  Generic multi-fidelity DSE
    is not enough.
  - **QE/DFT:** The current abstraction lacks broader QE workflow semantics,
    restart/reuse, richer artifacts, and measured inputs.
  - **FPGA/HLS:** The deployment grammar needs implementation-level knobs and
    real kernel paths; toy HLS package generation cannot support deployment DSE.
  - **Algorithm:** Current search is deterministic ranking over enumerable
    candidates; the stronger direction is hierarchical multi-fidelity
    BO/bandit with learned posteriors and value of information.
- **accepted changes:**
  - Accept `workflow mismatch` as the formal algorithmic object connecting
    workload abstraction to acquisition.
  - Accept promotion precision, mispromotion rate, and rank inversion under
    independent fidelity as first-class evaluation metrics.
  - Accept that the final paper must include a negative-control result where
    kernel-only or SCF-only rankings select a bad candidate because workflow
    effects dominate.
  - Accept that deployment grammar must expose package-level implementation
    knobs for the algorithm to be more than high-level planning.
- **rejected changes and reason:**
  - Reject proving the method only on synthetic independent mismatch.  Synthetic
    mismatch is useful for development but insufficient for DAC evidence.
  - Reject evaluating only promoted winners.  Non-promoted samples are required
    to estimate promotion precision/recall and rank correlation.
  - Reject using only final best EDP.  The paper needs budget curves,
    calibration, top-k hit, hypervolume, and feasibility survival.
- **unresolved risks:**
  - The mismatch model may be hard to train without enough independent fidelity
    samples.
  - Whole-QE coverage may be too broad for the first paper; the first proof path
    may need to state "representative QE workflow classes" while avoiding
    SCF-only completion.
  - Implementation-level grammar can explode the search space unless candidate
    generation is hierarchical.
- **evidence needed next:**
  - A table mapping each workflow-mismatch feature to a measurable source field,
    an expected cheap-model failure mode, and an ablation.
  - A benchmark protocol with promoted and non-promoted independent-fidelity
    samples.
  - A candidate grammar extension plan for FFT/transpose or bounded `h_psi`
    implementation knobs.
  - A measured corpus plan that is realistic but not unbounded.
- **current method version summary:** `WAMF-DSE v0.3` should be stated as
  workflow-mismatch-aware multi-fidelity promotion: a hierarchical candidate
  generator and posterior model use workflow graph features to predict L1/L2
  mismatch and allocate high-fidelity evaluations to candidates and fidelities
  with the highest Pareto and calibration value.
- **progress delta:** The method evolved from a workflow-aware search framework
  to a specific hypothesis: workflow features predict cheap-model rank
  inversions and therefore improve high-fidelity promotion efficiency.
- **technical verdict:** Stronger.  This gives the work a sharper, testable
  algorithmic thesis distinct from generic BO/NSGA-II.  It remains unproven
  until independent-fidelity promotion data exists.
- **next-iteration objective:** Produce an experiment matrix and implementation
  task map that connects each algorithm component to repository changes,
  required tests, and evidence artifacts.

## Iteration 3 - From Algorithm Thesis To Executable Evidence Roadmap

- **iteration_id:** `alg-iter-003`
- **timestamp:** `2026-06-02 18:07:17 +0800`
- **starting hypothesis:** A method-level contribution can be made credible if
  every algorithmic claim is paired with an executable experiment, baseline,
  ablation, and evidence level.
- **design question being tested:** What is the minimum evidence path that can
  prove WAMF-DSE is useful without overclaiming final FPGA acceleration?
- **sources/code/paper sections inspected:**
  - `docs/architecture/qe_fpga_dse_algorithm/evidence_and_experiment_plan.md`
  - `dse_v2/mapping/multifidelity_benchmark.py`
  - `dse_v2/tests/test_multifidelity_benchmark.py`
  - `dse_v2/tests/test_qe_fpga_deployment_dse.py`
  - `paper/dac_qe_fpga_dse/main.tex`
  - Expert reviews received during `alg-iter-001` and `alg-iter-002`.
- **algorithm changes proposed:**
  1. Make promotion precision/recall and mispromotion rate first-class metrics
     alongside regret, hypervolume, and top-k hit.
  2. Require promoted and non-promoted independent-fidelity samples; winner-only
     validation is insufficient.
  3. Separate method feasibility evidence from final hardware evidence.
  4. Use synthetic independent mismatch only as `E1`; measured QE and
     independent fidelity are required for the main DAC argument.
  5. Convert workflow-mismatch features into an ablation matrix so each claimed
     feature has a falsifiable effect.
- **expert-agent critiques received:**
  - DAC/EDA: prove workflow abstraction changes scarce high-fidelity promotion.
  - QE/DFT: measured corpus and richer workflow semantics are mandatory.
  - FPGA/HLS: real kernel package path is required before deployment claims.
  - Algorithm: deterministic selection tests are not search-quality evidence.
- **accepted changes:**
  - Accept the evidence-level ladder `E0` through `E5`.
  - Accept the minimal credible path: measured workflow corpus, equal-budget
    baselines, independent promoted/non-promoted samples, at least one real HLS
    C-sim/C-synth path, and calibration feedback.
  - Accept that the first paper can claim method feasibility and promotion
    efficiency, but not final FPGA speedup unless `E5` exists.
- **rejected changes and reason:**
  - Reject using package generation alone as implementation evidence.
  - Reject using L2 Python/TLM-only oracle as final method superiority evidence.
  - Reject a paper story with provenance tables as the main results.
- **unresolved risks:**
  - The measured corpus may be the schedule bottleneck.
  - Independent fidelity may be sparse; the experiment design must remain
    statistically honest under small samples.
  - If no real HLS kernel path closes, the paper must stay a method/planning
    paper rather than a deployment result.
- **evidence needed next:**
  - Implement or update tests for workflow DAG branch semantics and stage-local
    compute weights.
  - Build the mismatch-feature extractor and include it in search reports.
  - Add promotion precision/mispromotion metrics to benchmark reports.
  - Prepare a measured QE workflow bundle/corpus ingestion runbook.
  - Define a first real kernel package target and golden-vector source.
- **current method version summary:** `WAMF-DSE v0.3` is now a testable
  method-level hypothesis with a concrete evidence plan.  It remains incomplete
  until the repository implements mismatch features, stronger workflow graph
  semantics, independent-fidelity sampling, and real implementation feedback.
- **progress delta:** The work evolved from formal algorithm definition to an
  evidence roadmap that can prove or falsify the method without conflating
  method evidence with hardware claims.
- **technical verdict:** Stronger, still not complete.  The goal's requested
  multi-round design artifacts now exist, but the next phase must connect them
  to code, tests, measured workloads, and independent evidence.
- **next-iteration objective:** Implement the first semantic fixes and method
  instrumentation: workflow DAG correctness, stage-local weights, mismatch
  features, and promotion/mispromotion metrics.

## Iteration 4 - From Method Skeleton To Executable Algorithm Contract

- **iteration_id:** `alg-iter-004`
- **timestamp:** `2026-06-02 18:22:36 +0800`
- **starting hypothesis:** The design package is now strong enough as a
  research direction, but still too loose as an executable algorithm.  To make
  it defensible to DAC and algorithms reviewers, `p_m`, `VOI`, sparse-label
  evaluation, and the first implementation experiment must be specified more
  concretely.
- **design question being tested:** Is WAMF-DSE now a complete algorithmic
  method, or still a well-motivated acquisition heuristic with missing
  estimators and validation protocol?
- **sources/code/paper sections inspected:**
  - `docs/architecture/qe_fpga_dse_algorithm/formal_algorithm_v0_3.md`
  - `docs/architecture/qe_fpga_dse_algorithm/evidence_and_experiment_plan.md`
  - `docs/architecture/qe_fpga_dse_algorithm/method_design_v0.md`
  - `dse_v2/mapping/multifidelity_active_search.py`
  - `dse_v2/mapping/search_policy.py`
  - `dse_v2/mapping/multifidelity_benchmark.py`
  - `dse_v2/reference_workloads/qe_workflow_fpga_abstraction.py`
  - `dse_v2/reference_workloads/qe_mainflow.py`
  - `dse_v2/reference_workloads/qe_fpga_deployment_dse.py`
  - Current DAC 2026 research manuscript requirements.
  - Public descriptions of MAESTRO, Timeloop, ZigZag, multi-fidelity
    accelerator DSE, surrogate-assisted DSE, and generative/inverse DSE.
- **algorithm changes proposed:**
  1. Add a first executable contract for `p_m(x,w)` as a calibrated
     mispromotion classifier over measurable workflow, candidate, and
     interaction features.
  2. Add a first executable contract for `VOI_t(f | x,w)` that decomposes
     frontier information gain, calibration reuse, gate-resolution value, and
     prerequisite risk.
  3. Tie rank inversion to constrained Pareto usefulness, not only pairwise
     objective order.
  4. Add a sparse-label protocol: fixed candidate pool, paired ablations,
     promoted and deliberately non-promoted independent samples, budgets
     `2/4/8/...`, bootstrap confidence intervals, and leave-workload-out
     validation.
  5. Downgrade neural models from the first implementation default to a
     supporting option; start with engineered-feature residual ensembles or GP
     residuals, then move to graph neural models only when labels justify them.
  6. Make the next implementation artifact a measured full-QE workflow fixture
     that round-trips through `workflow_feature_contract` and Step2 search,
     not a bitstream attempt.
- **expert-agent critiques received:**
  - **DAC/EDA:** Novelty is weak today but potentially defensible if the work
    proves workflow-mismatch-aware promotion.  The current docs define a method
    shape but not yet an operational estimator/training/update protocol.
  - **Algorithms/DSE:** Implementation is still deterministic scoring with
    fixed weights and metadata-driven fidelity terms.  `p_m`, `VOI`, posterior
    update, rank inversion, and sparse-label evaluation need executable
    definitions.
  - **QE/DFT + FPGA/HLS:** The abstraction is broader than SCF/h_psi on paper
    but concrete code remains a QE-mainflow seed with coarse FPGA families.
    The top next artifact is a measured full-QE workflow fixture, not Vivado
    closure.
- **accepted changes:**
  - Accept the reviewer verdict: current status is a DAC-reviewable method
    proposal and roadmap, not a DAC-ready algorithm result.
  - Accept that WAMF-DSE must be evaluated with paired equal-budget ablations
    where the candidate generator is held fixed and workflow features are
    removed one group at a time.
  - Accept that "QE workflow" should be stated as "representative QE workflow
    classes" until measured non-SCF, post-processing, branch/reuse, and
    artifact-rich fixtures exist.
  - Accept that generated implementation packages are handoff artifacts until
    real kernel semantics, golden vectors, HLS C-sim/C-synth, and Vivado gates
    close.
  - Accept a conservative surrogate path: bootstrapped residual models, GP
    residuals, or small calibrated MLP ensembles over engineered features
    before graph transformers.
- **rejected changes and reason:**
  - Reject making the first next step a bitstream.  The algorithmic thesis is
    still blocked by workload semantics and promotion-efficiency evidence.
  - Reject relying on graph neural networks as novelty.  Label scale and
    independent-fidelity coverage are insufficient.
  - Reject "active search" wording for the implementation until posterior and
    VOI behavior are implemented.
  - Reject whole-QE or final-FPGA claims from current model-level and package
    scaffolding evidence.
- **unresolved risks:**
  - Sparse independent-fidelity labels may make statistical evidence fragile.
  - The mismatch classifier may learn benchmark artifacts unless candidate pool
    construction and ablations are paired and fixed.
  - Representative QE workflow classes may still be too broad for one DAC paper
    unless the first corpus is small but carefully stratified.
  - The first HLS kernel path may fail to close, forcing the paper to remain a
    method/promotion-efficiency paper rather than a deployment-result paper.
- **evidence needed next:**
  - Measured full-QE workflow fixture with SCF, NSCF, post-processing fan-out,
    relax or vc-relax, artifact lifetimes, restart/reuse, and correctness
    observables.
  - Executable mismatch-feature extractor and report schema.
  - Closed-loop promotion-efficiency benchmark with WAMF, no-workflow-risk,
    L1-only, kernel-hotspot-only, SCF-only, random, BO/EI, NSGA-II/III, and
    Hyperband baselines under identical budgets.
  - Independent oracle subset containing promoted and non-promoted candidate
    samples, with bootstrap intervals.
  - First real QE-derived kernel package target and golden-vector source after
    the algorithm benchmark is in place.
- **current method version summary:** `WAMF-DSE v0.3.1 target` is a
  workflow-mismatch-aware multi-fidelity promotion method with an executable
  first estimator contract: calibrated residual objective model, calibrated
  mispromotion classifier, VOI-based fidelity action selection, paired
  sparse-label ablations, and measured workflow fixtures.
- **progress delta:** The work evolved from a plausible formal method skeleton
  to a concrete first implementation and evaluation contract.  The main advance
  is that `p_m`, `VOI`, and "workflow matters" now have falsifiable operational
  definitions instead of remaining descriptive terms.
- **technical verdict:** Stronger at the algorithm-design level; still
  unproven at the result level.  The next phase can now implement and test a
  narrow algorithm benchmark without pretending to have hardware evidence.
- **next-iteration objective:** Implement the first executable algorithm
  artifacts: measured workflow fixture ingestion, mismatch-feature extraction,
  residual/posterior interface, VOI fidelity scoring, and sparse-label
  promotion-efficiency benchmark.
