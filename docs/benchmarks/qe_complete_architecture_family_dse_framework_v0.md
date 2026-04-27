# QE complete architecture-family DSE framework v0

## 1. Purpose

This document defines the intended architecture-family design-space exploration framework for the QE band-solver acceleration stack. It is a complete system description, not a patch note over the current runner. It starts from the workload, architecture, mapping, evaluator, calibration, and reporting objects that a scientific-computing DSE flow needs, then binds each object to the repository surfaces that already exist.

The framework is intentionally evidence first. In the current Stage A state, DSE outputs can rank, screen, explain, and nominate candidates for later checks. They cannot make final performance claims, GPU comparison claims, board-grounded claims, or thesis-grade architecture decisions. Those boundaries stay frozen by `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md`, `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md`, and `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`.

The companion machine-readable files are:

* `docs/benchmarks/qe_architecture_family_design_space_schema_v0.json`
* `docs/benchmarks/qe_architecture_family_design_space_spec_v0.json`

The JSON spec is the executable design-space intent. This Markdown file explains the model and the authority policy around it.

## 2. Local anchors and current truth

The framework is grounded in these repository anchors.

| Anchor | Local file or hook | Role in this framework |
| --- | --- | --- |
| Current architecture-family runner | `docs/benchmarks/run_systemc_architecture_family_dse_sweep.py` | Produces `F1`, `F2`, and `F3` sweep rows plus template-driven scaffold rows, `family_summary`, projection flags, graph evidence, gold gate artifacts, and CSV or JSON bundles. |
| Result schema | `docs/benchmarks/systemc_architecture_family_dse_result_schema_v0.json` | Defines the current bundle shape consumed by phase, release, and adjudicator layers. |
| Template loader | `docs/benchmarks/architecture_template_loader.py` | Loads and validates architecture templates against `docs/architecture/architecture_template_schema_v1.json`. |
| Candidate generator | `docs/benchmarks/architecture_candidate_generator.py` | Produces grid, random, and Latin-hypercube candidate variants from templates. |
| Template projector | `docs/benchmarks/template_to_systemc_config.py` | Projects architecture templates to SystemC configuration JSON. |
| Runtime config hook | `model/qe_band_solver_model/sc_main.cpp`, `QEBS_ARCH_CONFIG` | Lets the runnable model load an external architecture config JSON. The same entry also accepts `QEBS_*` workload, family, policy, and graph-frontdoor fields. |
| Graph projection helper | `docs/benchmarks/qe_ic_graph_projection_utils.py` | Exports graph/component specs into design-point keys, shared join keys, and `SystemRunConfig` graph-frontdoor patches. |
| Graph projection contract | `docs/architecture/qe_ic_component_graph_projection_v1.md` | Freezes the intended mapping from `component_catalog + graph_spec` to design point, join keys, and runtime frontdoor fields. |
| Component catalog and graph seed | `docs/architecture/qe_ic_component_catalog_system_level_v1.json`, `docs/architecture/qe_ic_graph_seed_system_level_v1.json` | Canonical system-level component library and balanced F2 seed. |
| Fidelity ladder | `docs/benchmarks/qe_dse_fidelity_ladder_and_execution_loop_v0.md` | Defines the low-cost, fast-layer, accurate-layer, generalization, and release or authority layers. |
| Phase config | `docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json` | Freezes fast-layer objectives, accurate-layer checks, state machine, promotion policy, and tie-band rule. |
| Calibration contract | `docs/benchmarks/qe_ic_simulator_calibration_contract_v0.md` | Defines descriptor fields, calibration ownership, join-key export rules, and fast versus numerically grounded lanes. |
| Correctness and fairness contracts | `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md`, `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md` | Keep workload, tolerance, timing, power, rewrite, and GPU baseline comparisons comparable. |
| Adjudicator contract | `docs/benchmarks/qe_ic_adjudicator_authority_contract_v0.md` | Keeps DSE, GPU annex, projection, phase closure, and stage recommendation surfaces as evidence only. |
| QE workload evidence | `docs/overview/qe_subspace_sampling.md`, `docs/benchmarks/summarize_qe_subspace_trace.py`, `docs/benchmarks/qe_kernel_characterization_matrix_for_system_dse_v0.md`, `docs/benchmarks/qe_partition_and_interface_for_system_dse_v0.md`, `docs/benchmarks/qe_dse_parameter_stack_for_system_dse_v0.md` | Provides trace, signature, partition, and parameter evidence for the workload IR. |

The requested `dse_v2` Bayesian-optimization proof of concept is treated as a future candidate-proposal layer named `dse_v2_bo_poc`. It may consume DSE result bundles and propose new candidate points, but it does not replace the runner, contracts, promotion gates, accurate layer, or adjudicator. No current Stage A report may treat a Bayesian proposal as a claim-bearing result unless it is projected back through the same schema, evaluated through the same fidelity ladder, and admitted by the same authority rules.

## 3. Framework object model

The complete DSE system has seven first-class IRs.

### 3.1 Workload IR

The workload IR describes a QE case before any architecture is chosen. It exists to make the scientific workload explicit and to stop architecture rows from hiding workload drift.

Required identity fields:

* `workload_id`
* `workload_group_id`
* `software_family`
* `flow_family`
* `qe_tolerance_schema_id`
* `accounting_boundary_id`
* `fairness_policy_id`
* `power_boundary_id`
* `observability_contract_id`

Required signature fields mirror the calibration contract:

* `signature_id`
* `property_target`
* `pseudopotential_family`
* `solver_path_class`
* `workload_topology`
* `post_scf_extension_level`
* `projector_pressure`
* `nonlocal_pressure`
* `generalized_ratio_bucket`
* `diag_dominance`
* `fft_grid_pressure`

The workload IR also records shape evidence. The current QE evidence chain centers the system object on `electrons -> c_bands`, with `h_psi`, `s_psi`, `build H_sub/S_sub`, `cdiaghg`, and `refresh/residual -> P_next` as the main band-solver stages. The 4-cluster split in the architecture docs uses the working shares A operator sweep 68 percent, B reduced build 4 percent, C diag 23 percent, and D refresh/residual 5 percent as design-pressure guidance. These numbers are workload-characterization anchors, not final performance claims.

### 3.2 Architecture graph and template IR

The architecture IR has two compatible surfaces.

The graph surface is the system-level component graph. It contains modules, links, flows, placement, constraints, and join keys. The current canonical graph files are `qe_ic_component_catalog_system_level_v1.json` and `qe_ic_graph_seed_system_level_v1.json`. The graph projection contract maps this graph to five claim-bearing design-point keys:

* `family`
* `diag_policy`
* `offload_scope`
* `resident_policy`
* `partition_strategy`

The template surface is the architecture-template flow used by existing utilities. `architecture_template_loader.py` validates the template, `architecture_candidate_generator.py` creates candidate variants, and `template_to_systemc_config.py` projects a template to a SystemC architecture configuration sidecar. The current framework keeps this template flow as a valid producer of architecture config JSON, but projection is not the same as executor support. A template becomes runtime-executor-backed only when the runnable SystemC path consumes its projected config for the same workload/join keys and emits comparable runtime metrics. Until then, the row remains a Stage-A proposal or scaffold row.

The complete template catalog currently contains these fourteen JSON templates:

| Template ID | Family | Runtime projection family | Stage-A role | Executor boundary |
| --- | --- | --- | --- | --- |
| `4cluster_cim_baseline_v1` | `F2` | `F2` | Baseline template | Current balanced CIM-oriented 4-cluster template; evidence-only under Stage A. |
| `4cluster_traditional_fpga_v1` | `F2` | `F2` | Baseline template | F2 runtime-family projection with template-specific DSP assumptions; comparable only when runtime metrics are emitted. |
| `f1_host_heavy_cpu_baseline_v1` | `F1` | `F1` | Baseline scaffold | Host-heavy CPU/reference scaffold; disabled-cluster and host-heavy semantics remain projection metadata unless comparable runtime rows are emitted. |
| `f2_systolic_fpga_dense_path_v1` | `F2` | `F2` | Primary scaffold | Systolic dense-path F2 scaffold; dense-path assumptions are Stage-A metadata until backed by runtime metrics. |
| `f3_tensor_systolic_fpga_offload_v1` | `F3` | `F3` | Primary scaffold | Device-heavy tensor-systolic FPGA scaffold; fabric assumptions require explicit runtime support before executor claims. |
| `f3_hbm_streaming_operator_pipeline_v1` | `F3` | `F3` | Primary scaffold | HBM streaming operator-pipeline scaffold; HBM/streaming semantics are proposal metadata until runtime-backed. |
| `3cluster_fused_build_diag_v1` | `F4` | `F2` | Conditional scaffold | Projection-only fused build+diag scaffold unless a fused executor is implemented and validated. |
| `cim_dsp_vector_hybrid_v1` | `F4` | `F2` | Primary scaffold | Projection-only CIM/DSP vector hybrid scaffold; hybrid semantics are metadata unless runtime-backed. |
| `f4_cim_dsp_hbm_hybrid_v1` | `F4` | `F2` | Primary scaffold | Projection-only CIM/DSP/HBM hybrid scaffold; no completed hybrid executor support is claimed. |
| `unified_fp64_gemm_fabric_v1` | `F5` | `F2` | Primary scaffold | Projection-only unified FP64 GEMM fabric scaffold; no completed scheduler/executor support is claimed. |
| `f5_cgra_dataflow_operator_v1` | `F5` | `F2` | Primary scaffold | Projection-only CGRA dataflow scaffold; fused operator/build scheduling requires a future executor. |
| `resident_dataflow_fabric_v1` | `custom` | `F2` | Conditional scaffold | Projection-only resident-dataflow/PIM scaffold; resident and PIM behavior are not completed runtime semantics. |
| `custom_multichiplet_noc_partition_v1` | `custom` | `F2` | Conditional scaffold | Projection-only multi-chiplet/NoC partition scaffold; placement, communication, and packaging semantics are metadata only. |
| `custom_near_memory_pim_resident_v1` | `custom` | `F2` | Conditional scaffold | Projection-only near-memory PIM resident scaffold; residency and PIM behavior need future executor and board evidence before runtime or power claims. |

This table is deliberately conservative. `F4`, `F5`, `custom`, and any newly added template IDs are projection/scaffold rows unless a future work package adds runtime executor support and validates it through the same result schema, fidelity ladder, and adjudicator boundary. Template metadata does not override graph join keys, fairness/power contracts, correctness contracts, or adjudicator outputs.

The seed families and scaffold families retain these current meanings:

| Family | Meaning | Current DSE role |
| --- | --- | --- |
| `F1` | Host-heavy or single-hotpath | Low-coupling convergence and fallback reference. |
| `F2` | Balanced hybrid or multi-operator pipeline | Canonical 4-cluster balanced system seed. |
| `F3` | Device-heavy or full inner-loop offload | Conditional higher-complexity family that needs stronger closure before promotion. |
| `F4` | Fused or CIM-DSP hybrid scaffold | Stage-A projection-only template family for fused build or hybrid CIM/DSP variants. |
| `F5` | Unified FP64 GEMM fabric scaffold | Stage-A projection-only template family for shared operator/reduced-build GEMM fabric hypotheses. |
| `custom` | Resident dataflow or PIM-style scaffold | Conditional projection-only family for aggressive residency and PIM-style experiments. |

### 3.3 Mapping and schedule IR

The mapping IR binds workload stages to architecture resources. At the system level it must state:

* which stages remain host-owned, for example `rho -> Veff`, outer SCF, mix and convergence, and diag fallback;
* which stages are hardware-owned, for example `h_psi`, `s_psi`, reduced build, hardware-first diag proxy, refresh and residual;
* whether diag is `cpu_only`, `device_first_fallback`, or `aggressive_device`;
* whether the offload scope is `single_hotpath`, `balanced`, or `device_heavy`;
* whether resident objects follow `fit_first` or `spill_tolerant` policy;
* what cluster sequence is requested and what sequence is resolved by the current runtime.

The runtime-facing schedule is exposed through `SystemRunConfig` and `ScfIterationRequest` fields. The current `sc_main.cpp` hook reads `QEBS_ARCH_CONFIG` for architecture config JSON, plus environment fields such as `QEBS_ARCH_FAMILY`, `QEBS_OFFLOAD_SCOPE`, `QEBS_RESIDENT_POLICY`, `QEBS_GRAPH_FRONTDOOR_MODE`, `QEBS_GRAPH_ID`, `QEBS_GRAPH_REQUESTED_CLUSTER_SEQUENCE`, and `QEBS_GRAPH_RESOLVED_CLUSTER_SEQUENCE`. This is the brownfield entry for generated DSE configurations.

### 3.4 Evaluator IR

Every evaluator must declare its fidelity, source kind, inputs, outputs, and authority limit.

The intended evaluator ladder is:

| Layer | Evaluator class | Current local anchor | Allowed output |
| --- | --- | --- | --- |
| A | Characterization and pruning | QE trace summaries, workload matrix scripts, kernel characterization docs | Workload shape, hotpath, candidate axes, infeasibility filters. |
| B | Fast timed-functional system search | `run_systemc_architecture_family_dse_sweep.py`, `run_qe_next_stage_dse_phase.py`, `model/qe_band_solver_model/build/qe_band_solver_model` | Ranking, family summaries, row state, shortlist inputs. |
| C | Correctness-capable accurate layer | `compare_qe_gold_correctness.py`, `normalize_qe_gold_baseline.py`, gold/tolerance artifacts | Gold pass, convergence comparable pass, final energy, final convergence fields. |
| D | Nonblocking generalization | phase runner coverage lanes | Broader workload confidence notes. |
| E | Release and authority layer | adjudicator and closure contracts | Claim permission and public posture, only through adjudicator authority. |

The fast layer ranks by `time_to_convergence_s` first and `energy_to_convergence_j` second. It also tracks `bytes_moved_to_convergence`, `fallback_ratio`, and `spill_ratio`. A row with missing core metrics or `ranking_grade_ready != true` is explain-only, not promotion-ready.

### 3.5 Calibration feedback IR

Calibration links fast proxy rows to stronger evidence without changing their identity. It records:

* trace-shape source and summary;
* proxy assumption set;
* source kind, using the existing taxonomy `stub`, `timed_functional_proxy`, `trace_calibrated_proxy`, `measured`, or `mixed`;
* gold bundle or correctness source;
* GPU baseline readiness state;
* board or whole-node evidence state when available;
* calibration residuals and uncertainty intervals once measured evidence exists.

The calibration contract keeps the baseline phase config as authority for the two-layer scaffold and treats IC overlays as derived overlays until their exporter preserves family semantics, fast or accurate layer semantics, and join keys without alias drift.

### 3.6 Pareto and promotion reporting IR

The reporting IR separates mathematical tradeoff reporting from claim authority.

Allowed Stage A reporting:

* row-level metrics and missing fields;
* Pareto membership over time, energy, bytes, fallback ratio, spill ratio, or resource use;
* `reject`, `explain-only`, and `promotion-eligible` state counts;
* primary candidate, fallback candidate, and extra candidates inside the configured tie band;
* family summaries with projection confidence;
* contradiction and blocker notes for adjudicator intake.

Forbidden Stage A reporting:

* final public best-family selection;
* final `CPU + FPGA` beats `CPU + GPU` statements;
* lower whole-node power claims without the frozen power boundary evidence;
* board-grounded causality from proxy rows;
* treating `dse_v2_bo_poc` proposals as evaluated results.

The promotion state machine remains the one frozen in `qe_next_stage_dse_simulator_phase_config_v0.json`: `reject`, `explain-only`, `promotion-eligible`, with a relative time tie-band after energy tiebreak at 0.05.

### 3.7 Authority IR

The authority IR records who may say what.

* DSE runner: may produce rows, rankings, summaries, projection fields, gold-gate helper outputs, and evidence bundles.
* Phase runner: may assemble fast-layer, accurate-layer, coverage, and package surfaces.
* GPU and board evidence producers: may add measured rows only under the frozen correctness, fairness, power, and observability contracts.
* Adjudicator: the only layer allowed to turn evidence into public family decision, release posture, and claim permission.

If trusted-family and performance-family diverge, Stage A must not publish a family winner. The DSE system may still show the divergence as evidence.

## 4. End-to-end execution flow

The intended full flow is:

1. Load workload descriptors and trace-shape evidence.
2. Load component catalog, graph spec, and optional architecture templates.
3. Project graph and template surfaces into design-point keys, join keys, runtime config patches, and graph sidecar evidence.
4. Generate candidate points through grid, random, Latin-hypercube, or future `dse_v2_bo_poc` proposal loops.
5. Reject candidates that violate schema, resource, policy, fairness, observability, or join-key constraints before execution.
6. For runnable candidates, generate runtime config JSON and invoke the model only when the campaign explicitly allows it. In this docs-only package, no model execution is requested.
7. Normalize row outputs into the result schema and compute fast-layer metrics.
8. Classify rows as `reject`, `explain-only`, or `promotion-eligible`.
9. Select primary, fallback, and tie-band candidates.
10. Promote only shortlisted points to correctness-capable validation.
11. Add calibration feedback and update uncertainty metadata without rewriting row identity.
12. Report Pareto, promotion, blockers, and evidence bundles to the adjudicator.
13. Let the adjudicator decide public posture and claim permission.

### 4.1 Stage-A template-driven exploration flow

The bounded Stage-A template flow is:

1. Load `docs/benchmarks/qe_architecture_family_design_space_spec_v0.json` and the template JSON files under `docs/architecture/architecture_templates/`.
2. Validate required template fields, record template hashes, and attach template ID, family, risk, validation-status, and projection metadata to each row.
3. Project each template into the five design-point keys (`family`, `diag_policy`, `offload_scope`, `resident_policy`, `partition_strategy`) plus optional `QEBS_ARCH_CONFIG` sidecars.
4. Preserve the projection/executor boundary: `F4`, `F5`, `custom`, and future new templates map to scaffold/projection rows unless a runtime executor explicitly supports their fused, hybrid, resident, or PIM semantics.
5. Enumerate only the requested workload/template combinations, using `--max-design-points` for bounded smoke runs.
6. Emit JSON, CSV, projected config sidecars when requested, and the Stage-A coverage/readiness manifest.
7. Classify rows as `reject`, `explain-only`, or `promotion-eligible` according to the existing state machine, without naming a final architecture winner.
8. Treat the result bundle as adjudicator intake evidence, not as public decision authority.

A reproducible bounded smoke command is:

```bash
python3 docs/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --template-driven \
  --architecture-template-dir docs/architecture/architecture_templates \
  --architecture-template-ids \
    4cluster_cim_baseline_v1 \
    4cluster_traditional_fpga_v1 \
    f1_host_heavy_cpu_baseline_v1 \
    f2_systolic_fpga_dense_path_v1 \
    f3_tensor_systolic_fpga_offload_v1 \
    f3_hbm_streaming_operator_pipeline_v1 \
    3cluster_fused_build_diag_v1 \
    cim_dsp_vector_hybrid_v1 \
    f4_cim_dsp_hbm_hybrid_v1 \
    unified_fp64_gemm_fabric_v1 \
    f5_cgra_dataflow_operator_v1 \
    resident_dataflow_fabric_v1 \
    custom_multichiplet_noc_partition_v1 \
    custom_near_memory_pim_resident_v1 \
  --workloads si4_pbe_uspp_small graphene_pbe_uspp \
  --max-design-points 28 \
  --emit-projected-configs \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --source-kind stub \
  --output-dir tmp/stage_a_template_dse_smoke
```

This command is intentionally bounded to fourteen templates times two QE workload proxies and intentionally omits `--execute-model`. It validates the template-driven catalog and projection sidecars, but it does not assert completed SystemC executor support for new scaffold templates, F4/F5/custom templates, or any runtime-specific fabric semantics, and it does not produce final architecture-winner claims.

## 5. `dse_v2_bo_poc` integration rule

The Bayesian-optimization proof of concept is deliberately downstream of the existing evidence chain. Its role is proposal generation, not authority.

Inputs:

* past DSE rows that already satisfy the result schema;
* normalized design-point vectors from the JSON design-space spec;
* objective fields already defined by the phase config;
* constraint and state labels from the fast layer;
* uncertainty fields from calibration feedback when available.

Outputs:

* proposed candidate vectors;
* acquisition-score metadata;
* explanation of which prior rows informed the proposal;
* no performance result until the candidate is evaluated by the same ladder.

Guardrails:

* It must not mutate frozen contracts.
* It must not skip `QEBS_ARCH_CONFIG` or graph-frontdoor projection when targeting the runnable model.
* It must not claim promotion eligibility before the normal state machine runs.
* It must emit reproducible seeds and candidate IDs.
* It must stay optional until the rule-based and accurate-layer chain is stable enough to provide training data.

## 6. First QE DSE campaign

The first campaign defined by the companion spec is `qe_arch_family_stage_a_campaign_v0`.

Scope:

* Software family: `QE`
* Primary families: `F1`, `F2`, `F4`, `F5`
* Conditional families: `F3`, `custom`
* Main fast-layer cases: `si4_pbe_uspp_small`, `graphene_pbe_uspp`
* Correctness anchor: `si8_pbe_nc`
* Canonical coverage: `si8_pbe_uspp`
* Nonblocking generalization: `si4_pbe_uspp_small`, `graphene_pbe_uspp`, `graphene_pbe_paw`, `h2_tiny`

Design axes:

* `family`: `F1`, `F2`, `F3`, `F4`, `F5`, `custom`
* `diag_policy`: `cpu_only`, `device_first_fallback`, `aggressive_device`
* `offload_scope`: `single_hotpath`, `balanced`, `device_heavy`
* `resident_policy`: `fit_first`, `spill_tolerant`
* `partition_strategy`: `single_hotpath_partition`, `operator_build_fused__diag__refresh`, `operator__build__diag__refresh`, `operator__build_diag_fused__refresh`, `operator_build_fused__diag_refresh_fused`

Metrics:

* Primary objective: `time_to_convergence_s`
* Secondary objective: `energy_to_convergence_j`
* Constraints and explanations: `bytes_moved_to_convergence`, `fallback_ratio`, `spill_ratio`, resource estimates, correctness status, convergence status, source kind, and projection confidence

Stage-A expected result:

* A validated design-space definition and campaign plan.
* Schema-valid machine-readable spec.
* Evidence-only DSE reporting plan.
* Bounded template-driven Stage-A smoke flow that includes all six current architecture templates.
* Explicit projection/executor boundary for F4/F5/custom/new templates.
* No new final performance claims.
* No change to C++ runtime or existing frozen contracts.

## 7. File ownership and update policy

This work package owns only the workflow document and companion design-space catalog named at the top of this task. It does not update templates, runners, C++ runtime, tests, timestamped artifacts, or frozen contracts.

Future implementation work may add adapters, validators, or `dse_v2_bo_poc` code, but those changes must be separate work packages with their own validation and authority review.
