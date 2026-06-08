# QE Workflow-to-FPGA DSE Algorithm Package

Status: algorithm-level design package after four explicit iterations.

This directory records the current research-method design for WAMF-DSE:
Workflow-Mismatch-Aware Multi-Fidelity Deployment DSE.  It is a method
proposal and implementation roadmap, not a DAC-ready result and not a hardware
acceleration claim.

## Current Verdict

**Partially correct, stronger than the previous scaffold, not yet proven.**

The defensible thesis is:

> Workflow abstractions can predict cheap-model fidelity-mismatch modes in QE
> FPGA deployment, and using those mismatch signals can improve scarce
> high-fidelity promotion efficiency.

The current repository has useful workflow-aware DSE scaffolding and model-level
feedback, but it still lacks the measured workflow corpus, executable posterior
and value-of-information loop, independent-fidelity promotion evidence, and real
kernel HLS/Vivado closure needed for a DAC result.

## Documents

| File | Purpose |
| --- | --- |
| `algorithm_iteration_ledger.md` | Preserves each algorithm-design iteration, expert critique, accepted/rejected change, risk, and next direction. |
| `method_design_v0.md` | Defines the method shape: workflow abstraction, deployment grammar, fidelity ladder, surrogate role, action space, acquisition, blockers, and innovation boundary. |
| `formal_algorithm_v0_3.md` | Defines the current mathematical algorithm and the first executable contract for `p_m`, residual modeling, VOI, update, baselines, and completion boundaries. |
| `evidence_and_experiment_plan.md` | Defines evidence levels, baselines, metrics, ablations, sparse-label sampling, and the smallest credible algorithm paper path. |
| `expert_review_action_items.md` | Consolidates DAC/EDA, architecture, FPGA/HLS, QE/DFT, algorithms, neural surrogate, paper, and industry review actions. |

## Requirement Audit

| Goal Requirement | Status | Artifact |
| --- | --- | --- |
| At least 3 explicit algorithm iterations | Satisfied | `algorithm_iteration_ledger.md` contains iterations 1-4. |
| Preserve per-iteration evolution history | Satisfied | Each iteration records hypothesis, design question, inspected sources, critiques, accepted/rejected changes, risks, evidence, verdict, and next objective. |
| Clear method name | Satisfied | WAMF-DSE in `method_design_v0.md` and `formal_algorithm_v0_3.md`. |
| Complete method, not only acquisition | Satisfied at design level | Workflow abstraction, deployment grammar, fidelity ladder, candidate/fidelity action, calibration, feedback, and handoff are defined. |
| Formal variables, objectives, pseudocode | Satisfied at design level | `formal_algorithm_v0_3.md`. |
| Workflow abstraction beyond SCF/h_psi | Partially satisfied | Target semantics are defined; code remains QE-mainflow-centric and needs measured full-workflow fixtures. |
| Deployment grammar for FPGA choices | Partially satisfied | Family-level grammar exists; implementation-level HLS/Vivado knobs are still weak. |
| Baselines and ablations | Satisfied at design level | `evidence_and_experiment_plan.md` and `formal_algorithm_v0_3.md`. |
| Evidence plan for each conclusion | Satisfied at design level | Evidence levels E0-E5 and metric/ablation protocol are defined. |
| Multiple expert reviews | Satisfied for design phase | `algorithm_iteration_ledger.md` and `expert_review_action_items.md`. |
| Next implementation task list | Satisfied | `expert_review_action_items.md` and `evidence_and_experiment_plan.md`. |
| DAC-ready paper/result | Not satisfied | Requires measured corpus, closed-loop algorithm experiment, independent fidelity labels, and at least one real HLS path. |

## Current Method Boundary

The method may claim, after the next implementation phase and experiments:

- workflow-mismatch features improve promotion efficiency under a fixed
  high-fidelity budget;
- multi-fidelity feedback improves ranking/calibration relative to L1-only,
  kernel-only, SCF-only, generic BO/EI, NSGA-II/III, and Hyperband controls;
- the system produces candidate-specific implementation handoff packages.

The method must not claim yet:

- final FPGA speedup;
- whole-QE deployment completeness;
- neural-network superiority;
- DAC readiness;
- bitstream-backed acceleration.

Those claims require the evidence gates listed in
`evidence_and_experiment_plan.md`.

## Research Anchors Checked

The method boundary was checked against current DAC instructions and common DSE
patterns:

- DAC 2026 research manuscripts are six-page research-track submissions with
  strict formatting and review expectations:
  <https://dac.com/2026/speaker-resource-center/research-manuscripts-guidelines>
- MAESTRO represents analytical, data-centric cost-model DSE:
  <https://research.nvidia.com/publication/2020-04_maestro-data-centric-approach-understand-reuse-performance-and-hardware-cost>
- Timeloop represents systematic accelerator evaluation and mapping:
  <https://accelergy.mit.edu/timeloop.pdf>
- ZigZag represents memory-centric architecture/mapping DSE:
  <https://arxiv.org/abs/2007.11360>
- Theseus and Polaris represent recent multi-fidelity accelerator or
  architecture DSE:
  <https://arxiv.org/abs/2407.02079>,
  <https://arxiv.org/abs/2412.15548>
- DiffuSE and DiffAxE represent generative/inverse accelerator DSE:
  <https://arxiv.org/abs/2503.23945>,
  <https://arxiv.org/abs/2508.10303>

## Next Direction

The next phase should not chase bitstreams first.  The highest-leverage path is:

1. build a measured full-QE workflow fixture that round-trips through
   `workflow_feature_contract` into the Step2 search problem;
2. implement mismatch-feature extraction and report it in search traces;
3. implement the first residual posterior and VOI contract from
   `formal_algorithm_v0_3.md`;
4. run the paired promotion-efficiency benchmark with fixed candidate pools and
   equal budgets;
5. only then select one QE-derived kernel package for HLS C-sim/C-synth.
