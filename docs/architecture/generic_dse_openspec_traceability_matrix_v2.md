# Generic DSE OpenSpec Traceability Matrix v2

> **Date**: 2026-05-09  
> **OpenSpec change**: `enhance-generic-dse-framework-spec`  
> **Architecture document**: `docs/architecture/generic_dse_framework_design_spec_v2.md`  
> **Status**: Design-closure traceability baseline for P6 archive readiness; extended with active workload workflow, Step2, and Step3 implementation artifact contracts.

## Purpose

This matrix links the OpenSpec capability requirements to concrete sections in the professional architecture document. It is intended to support design review and later archive checks without requiring reviewers to infer whether a requirement is only a local evaluator feature or part of the full end-to-end DSE completion contract.

The top-level completion unit is the full closed-loop DSE run: workload ingestion, architecture catalog instantiation, mapping search, low-fidelity screening, SystemC or gem5+SystemC simulation, feedback update, evidence export, and a final analysis report whose trusted claims resolve to evidence.

## Source Artifacts

| Artifact | Role |
|---|---|
| `openspec/specs/**/*.md` | Normative OpenSpec requirements and scenarios after archive |
| `openspec/changes/archive/2026-05-09-enhance-generic-dse-framework-spec/proposal.md` | Archived what/why and impacted capabilities |
| `openspec/changes/archive/2026-05-09-enhance-generic-dse-framework-spec/design.md` | Archived system decisions, non-goals, risks, migration |
| `docs/architecture/generic_dse_framework_design_spec_v2.md` | Professional architecture/design manual |
| `openspec/changes/archive/2026-05-09-enhance-generic-dse-framework-spec/tasks.md` | Archived implementation and validation phasing |
| `openspec/changes/define-generic-workload-workflows/specs/**/*.md` | Active workload-family workflow requirements for later Step2+ implementation |
| `openspec/changes/define-step2-architecture-mapping-workflow/specs/**/*.md` | Active Step2 architecture/mapping workflow requirements for catalog, DesignPoint, legality, mapping search, promotion, and feedback handoff |
| `openspec/changes/define-step3-simulation-evidence-workflow/specs/**/*.md` | Active Step3 simulation/evidence workflow requirements for Step2 handoff replay, full-flow simulation, evidence artifacts, and blocked/untrusted gates |

## Capability-Level Traceability

| OpenSpec capability | Architecture document sections | Traceability notes |
|---|---|---|
| `generic-dse-ir-contract` | §3 Stage contract; §4.1 WorkloadPackage; §4.1.1 Generic ComputeGraph model; §4.4 DesignPoint; §8.2 run directory layout | Covers versioned workload/IR payloads, arbitrary computation graph semantics, replayable DesignPoint content, and persisted artifacts consumed by later stages. |
| `generic-workload-workflows` | §4.1.3 Workload-family workflow contract; §4.1.4 Workload workflow acceptance gates; §8.2 evidence contract; §9.3 claim evidence table | Defines per-family source, graph/lowering, mapping, simulation coverage, domain validation, and final claim-boundary profile requirements for ML/tensor, sparse, stencil/streaming, graph analytics, database/vector search, optional QE reference, and dynamic/custom workloads. |
| `step2-architecture-mapping-workflow` | §4.1.5 Step2 architecture/mapping audit contract; §4.2 Architecture catalog; §4.4 DesignPoint; §5 Mapping search design; §6 Screening and feedback loop | Defines the Step2 boundary after workload lowering and before simulation: inputs, architecture artifacts, DesignPoint completeness, legality matrix, seed ownership, candidate lifecycle, `step2_status.json`, `mapping_promotion_decision.json`, `step2_artifact_validation.json`, feedback handoff, and non-final gates. |
| `step3-simulation-evidence-workflow` | §4.1.6 Step3 simulation/evidence audit contract; §8 SystemC evidence contract; §9 final report gates | Defines the Step3 boundary after Step2 promotion: persisted Step2 input copy, pre-simulation trust gates, replayable `simulation_request.json`, full-flow evidence artifacts, `step3_status.json`, and smoke/diagnostic/prototype/predicted-only/candidate-only rejection. |
| `accelerator-system-description` | §4.2 Architecture catalog; §4.3 initial architecture families; §4.4 DesignPoint; §9.4 trusted ranking gate | Covers family/instance/binding separation, extensible architecture families, status labels, and binding-based trusted-final eligibility. |
| `multi-fidelity-dse-evaluation` | §5 Mapping search design; §6 Screening and feedback loop; §6.4 convergence criteria; §9.4 trusted ranking gate | Covers search space, legality matrix, candidate lifecycle, low-fidelity screening, SystemC-gated finalist ranking, and convergence/budget reporting. |
| `generic-simulation-backend` | §7 gem5 + SystemC role; §8 SystemC evidence contract; §9.3 claim evidence table | Covers L3/L4 boundaries, stub/prototype restrictions, evidence modes, manifest/verdict schemas, and backend evidence required for claims. |
| `dft-qe-workload-adapter` | Historical capability name; §2 System context; §4.1 WorkloadPackage domain metadata; §5.3 seed mappings; §9.1 final report sections | Keeps QE/DFT as an optional reference profile/importer while preserving generic IR and architecture contracts. |
| `end-to-end-dse-workflow` | §1 top-level completion definition; §3 top-level architecture; §5–§9 closed-loop search/evidence/report flow | Defines the complete DSE run as the archive-time acceptance unit, not isolated evaluator or stub execution. |

## Requirement Group Traceability

| Requirement group | Representative OpenSpec requirements | Architecture document coverage |
|---|---|---|
| Full run completion | End-to-end DSE run is the top-level completion unit; Pipeline stages have explicit inputs and outputs | §1.1, §1.2, §3, §3.1 |
| Workload and IR contracts | Versioned four-level IR stack; ComputeGraph is operator-agnostic and graph-shape neutral; graph lowering; TensorSpec defines units; profile-declared coverage; optional QE reference importer maps SCF workflow | §2.1, §3.1, §4.1, §4.1.1, §4.1.3, §4.1.4, §4.4, §8.2 |
| Architecture catalog | Accelerator self-description; SystemArchitecture composition; Architecture catalog schema separates family, instance, binding; Step2 architecture validation and trusted eligibility | §4.1.5, §4.2, §4.3, §4.4, §9.4 |
| Mapping search | Mapping search is algorithmic; Step2 consumes lowered executable graph; legality matrix; workflow-aware seed mappings; search operators; candidate lifecycle; mapping artifacts are persisted | §4.1.5, §5.1–§5.5, §8.2 |
| Step3 simulation/evidence | Step3 consumes persisted Step2 handoff artifacts; Step3 validates before simulation; Step3 reconstructs replayable request; Step3 emits full-flow evidence and structured status; Step3 cross-step validation covers generic profile/importer workflows | §4.1.6, §8.1–§8.4, §9.3–§9.4 |
| Multi-fidelity screening | L1/L2/L3/L4 evaluator boundaries; Promotion policy; Low-fidelity evaluators are candidate generators | §6.1–§6.4, §9.4 |
| Simulation feedback | Screening and simulation form a feedback optimization loop; High-fidelity results update screening models; Feedback loop stops by convergence criteria | §6.2–§6.4 |
| SystemC/gem5 backend | Simulation IPC; Python bridge; C++ parser; GraphExecutor; gem5 GenericAccel status boundary; full-flow pilot commands | §7.1–§7.3, §8.2–§8.4 |
| Evidence artifacts | Evidence artifacts are exported; Evidence modes define required artifact sets; Run artifacts support replay and audit; numeric simulator outputs are reference-checked | §8.1–§8.4 |
| Claim gating and reports | Final report links every claim to evidence; Report schema is machine-checkable; Predicted-only candidates cannot appear as winners; numerical correctness claims require explicit numerical evidence | §9.1–§9.4 |
| QE reference specialization | Optional QE SCF reference graph; QE-domain metrics; calibration notes; reference regression suite | §2.1, §2.2, §5.3, §8.2, §9.1, §9.3 |

## Review Checklist

- The professional architecture document defines the full end-to-end DSE run before subsystem details.
- Workload-family profiles define accepted sources, graph/lowering policy, mapping seeds, simulation coverage, profile/importer-domain validation, and claim boundary for each supported family and optional QE reference.
- Step2 architecture/mapping workflow defines the reviewable boundary between Step1 workload lowering and Step3+ simulation, including artifact completeness, architecture binding gates, legality matrix, seed ownership, candidate lifecycle, promotion decisions, artifact validation, and feedback handoff.
- Step3 simulation/evidence workflow defines the reviewable boundary after Step2 promotion, including copied Step2 inputs, pre-simulation blockers, replayable request generation, full-flow evidence/report artifacts, and structured `step3_status.json`.
- Cross-step tests must exercise Step1→Step2→Step3 continuity for representative generic workloads and the optional QE reference profile/importer, not only Step3-local fabricated inputs.
- Architecture families are extensible and binding-aware; legacy four-cluster/CIM designs are reference candidates, not the only default path.
- Mapping search and feedback are algorithmic, evidence-driven, and budget/convergence bounded.
- Trusted final rankings require SystemC or gem5+SystemC evidence and claim-to-evidence validation.
- Generic SystemC timing numeric results require `numerical_validation.json`; this remains scoped separately from QE FP64 physics correctness.
- Stub, blocked, predicted-only, candidate-only, and unsupported paths remain visible in reports and cannot be promoted to trusted winners.
- Smoke, diagnostic replay, fixed-timing, prototype, and driver/bring-up paths are explicit final-check failures unless complete full-flow evidence and claim validation are also present.
- Remaining user choices are recorded as discussion items rather than silently assumed by the design.
