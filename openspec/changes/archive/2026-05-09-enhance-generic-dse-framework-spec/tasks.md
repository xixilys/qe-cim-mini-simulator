## P0. SystemC Minimum Closed Loop and gem5+SystemC Boundary

- [x] P0.1 Define the minimal command path from gem5 software/driver to GenericAccel and into the SystemC backend: MMIO doorbell, descriptor/request payload, completion, status, and result handoff.
- [x] P0.2 Implement or bind a timing-level full-flow QE pilot workload through the standalone SystemC timing-level path, covering the SCF shell phases and not relying on fixed-timing-only results; gem5+SystemC remains blocked unless descriptor/completion evidence exists.
- [x] P0.3 Define the GenericAccel stub boundary: what is implemented, what is fixed timing, what is descriptor/DMA/TLM planned, and which claims are forbidden while stub mode remains.
- [x] P0.4 Add a full-flow validation that records SystemC backend invocation, timing execution, result artifact paths, and gem5+SystemC blocked/prototype status when command submission/completion is unavailable.
- [x] P0.5 Record explicit failure diagnostics for missing descriptor ingestion, unsupported DMA/result writeback, port wiring failures, or SystemC binding absence.

## P1. Evidence Artifacts and Claim Gating

- [x] P1.1 Define the run directory layout for summary, debug, and forensic evidence modes.
- [x] P1.2 Define `manifest.json`, `verdict.json`, `artifact_manifest.json`, and replay metadata schemas.
- [x] P1.3 Define required evidence files for each trusted SystemC/gem5+SystemC run: design point, architecture, mapping, workload graph, simulation request/result, logs, phase/resource/data summaries, and verdict.
- [x] P1.4 Define optional debug/forensic traces for finalists, failures, and user-selected runs: event timeline, task timeline, buffer occupancy, DMA trace, interconnect trace, scheduler decisions, assertion report, gem5 stats, and waveform/replay bundle where supported.
- [x] P1.5 Define claim-to-evidence validation rules so every final report claim references existing evidence files or is labeled predicted/untrusted/blocked.
- [x] P1.6 Define user artifact export rules: every referenced output path must be retrievable from the run directory or explicitly marked unavailable with reason.

## P2. Architecture Catalog and DesignPoint Completeness

- [x] P2.1 Define the architecture catalog schema: `ArchitectureFamily`, `ArchitectureParameter`, `ComponentType`, `ComponentInstance`, `ArchitectureInstance`, `ConstraintSet`, and `SimulationBinding`.
- [x] P2.2 Define architecture family extension rules so new Host/FPGA/Chip/CIM/GPU/ASIC/custom families can be added without modifying core DSE orchestration.
- [x] P2.3 Define the minimum DesignPoint payload: workload id, architecture instance, component parameters, memory hierarchy, interconnect topology, mapping, data placement, scheduling policy, precision policy, fallback policy, simulation config, and output config.
- [x] P2.4 Seed the initial architecture family list: CPU-only baseline, Host+FPGA minimal, Host+FPGA+CIM, diag-heavy, streaming-heavy, memory-rich, low-power, balanced, debug, and future custom.
- [x] P2.5 Define architecture status labels and eligibility: implemented, unverified, prototype, stub, planned, unsupported, candidate-only, and trusted-final-eligible.
- [x] P2.6 Define architecture validation checks for duplicate ids, missing simulation binding, unsupported operators, invalid units, memory/bandwidth/power/area violations, and absent communication routes.

## P3. Mapping Search Algorithm

- [x] P3.1 Define the mapping problem formally: workload DAG nodes, tensors, architecture resources, legal placements, data placement, schedule, fallback, and objective/constraint functions.
- [x] P3.2 Define legality matrix construction for operator support, precision support, memory capacity, communication route, data placement, and architecture-specific constraints.
- [x] P3.3 Define domain seed mappings for DFT/QE and generic workloads: host baseline, FPGA operator sweep, hardware diagonalization, all-operator offload, streaming, batch, CIM-heavy, and fallback mixes.
- [x] P3.4 Define mapping neighborhood operators: move, swap, fuse, split, stage-shift, data-place, schedule-shift, fallback-change, and architecture-parameter tweak.
- [x] P3.5 Define first implementation algorithm as domain-seeded beam/local search with L1/L2/surrogate screening and SystemC-gated finalist ranking.
- [x] P3.6 Define future optimization plug-ins for surrogate-assisted NSGA-II, Bayesian optimization, simulated annealing, and reinforcement/search-policy variants without changing evidence contracts.
- [x] P3.7 Define mapping artifacts: legality matrix, seed set, candidate mapping, search state, promotion reason, simulation sample, rejected candidate record, and selected mapping record.

## P4. Screening, Simulation Feedback, and Convergence

- [x] P4.1 Define screening outputs: predicted latency/energy/power/data movement/utilization, uncertainty, confidence, candidate family, selection reason, and promotion priority.
- [x] P4.2 Define candidate lifecycle states: generated, screened, promoted, scheduled-for-sim, simulated, rejected, finalist, selected, predicted-only, and blocked.
- [x] P4.3 Define feedback update logic that consumes SystemC/gem5+SystemC samples to update ranking, surrogate calibration, pruning thresholds, promotion policy, and next-candidate generation.
- [x] P4.4 Define promotion policy for Pareto-near candidates, high-uncertainty candidates, domain-seed coverage, constraint-boundary candidates, exploration quota, and user-pinned candidates.
- [x] P4.5 Define convergence criteria: trusted Pareto frontier stability, top-K stability, improvement threshold, uncertainty reduction, architecture-family coverage, and simulation budget exhaustion.
- [x] P4.6 Define budget and scheduling policy for expensive simulations, including top-K finalist reruns with evidence collection enabled.
- [x] P4.7 Define how low-fidelity mispredictions are recorded and used to downgrade confidence or adjust future search.

## P5. Final Analysis Report

- [x] P5.1 Define the final report schema: executive summary, workload, architecture catalog scope, search configuration, trusted ranking, Pareto alternatives, selected architecture/mapping, evidence index, limitations, and replay instructions.
- [x] P5.2 Define claim classes and evidence requirements for best architecture, mapping comparison, bottleneck diagnosis, feasibility, Pareto frontier, convergence, debug/replay, numerical correctness, and unsupported/stub limitations.
- [x] P5.3 Define trusted versus predicted-only report sections so L1/L2 candidates can be shown without being misrepresented as final conclusions.
- [x] P5.4 Define phase breakdown reporting for DFT/QE: operator sweep, reduced build, diagonalization, refresh/residual, density/mixing where modeled, and unavailable-metric labeling.
- [x] P5.5 Define report validation that checks every trusted claim has an evidence id, every evidence id resolves to files, and every referenced file exists or has an unavailable reason.
- [x] P5.6 Define final recommendation rules: selected design must be SystemC/gem5+SystemC-backed, feasible, not dominated in trusted metrics, and accompanied by explicit limitations.

Implementation evidence (2026-05-09):
- P3/P4 are implemented by `dse_v2/mapping/search.py` plus full-flow evidence export of `mapping_legality_matrix.json`, `mapping_seed_set.json`, `mapping_candidate_records.json`, `mapping_selected_record.json`, `mapping_simulation_samples.json`, and `mapping_feedback_state.json`.
- P5 is implemented by `dse_v2/reporting/final_report.py` and full-flow generation of `final_report.json`, `final_report.md`, `evidence_requirements.json`, and `claim_validation.json`.
- The top-level executable flow is `python3 dse_v2/scripts/dse/run_end_to_end_dse.py --workload qe_scf_shell --backend systemc --out runs/dse/<run_id>`; the gem5+SystemC path emits an explicit blocked/prototype verdict and descriptor/completion blocker artifacts when L4 is not runnable.
- Fresh validation evidence: `cmake --build model/generic_sim_backend/build -j4`, `python3 -m pytest -q dse_v2/tests`, and `openspec validate enhance-generic-dse-framework-spec --strict --no-color` all passed.

Post-audit hardening note (2026-05-09):
- Local OpenSpec design decisions 8, 9, and 11 require feedback and final reports to distinguish trusted high-fidelity samples from blocked/prototype attempts and to keep claim/evidence links resolvable.
- The implementation now treats blocked gem5+SystemC attempts as attempted-but-untrusted samples, validates externally supplied selected mappings against the legality matrix, and marks report/manifest artifacts generated in the current pass as resolvable in the final report evidence index.
- Remaining iteration target: replace the current single-sample seeded feedback prototype with a multi-candidate feedback loop that records frontier/top-K stability over multiple SystemC/gem5+SystemC samples before making comparative winner/Pareto claims.

## P6. Validation, Documentation, and Archive Readiness

- [x] P6.1 Update the professional architecture document with top-level flow diagrams, core data structures, architecture catalog schema, mapping algorithm, feedback loop, evidence contract, convergence criteria, and report schema.
- [x] P6.2 Update OpenSpec proposal/design/specs so the top-level objective is full end-to-end DSE execution and final analysis, not local evaluator completion.
- [x] P6.3 Create a requirement-to-document traceability table linking the OpenSpec capabilities to the professional architecture document sections.
- [x] P6.4 Run `openspec validate enhance-generic-dse-framework-spec --strict --no-color` and resolve all schema errors.
- [x] P6.5 Review scope compliance: no modifications under `dse_v2/`, `model/`, `gem5_integration/`, or `soft/qe-7.5/` for this design-only goal.
- [x] P6.6 Record remaining user-discussion items before implementation: architecture families to prioritize, first gem5+SystemC full-flow QE pilot workload, evidence verbosity defaults, and mapping-search budget.
- [x] P6.7 Split the next implementation work into separate goals for P0/P1, P2/P3, P4/P5, and validation/archive.

P6 closure evidence (2026-05-09):
- P6.1 is covered by `docs/architecture/generic_dse_framework_design_spec_v2.md`, including the closed-loop flow diagram, stage contract, core data structures, architecture catalog schema, mapping algorithm/artifacts, feedback sample classes, evidence contract, convergence criteria, and report validator gates.
- P6.2 is covered by updated OpenSpec proposal/design language and existing end-to-end workflow/multi-fidelity/backend specs that make full DSE execution and final analysis the top-level completion unit.
- P6.3 is covered by `docs/architecture/generic_dse_openspec_traceability_matrix_v2.md`.
- P6.4 validation command: `openspec validate enhance-generic-dse-framework-spec --strict --no-color` → `Change 'enhance-generic-dse-framework-spec' is valid`.
- P6.5 scope compliance review for this design-only closure: this pass modified only `docs/architecture/generic_dse_framework_design_spec_v2.md`, `docs/architecture/generic_dse_openspec_traceability_matrix_v2.md`, and OpenSpec proposal/design/tasks files. The working tree already contained unrelated `dse_v2/` implementation changes before this P6 design pass; they are not claimed as part of this closure and were not reverted or edited here. This pass did not modify `model/`, `gem5_integration/`, `runtime_api/`, or `soft/qe-7.5/`.
- P6.6 remaining user-discussion items are recorded in `docs/architecture/generic_dse_framework_design_spec_v2.md` §12 and summarized below.
- P6.7 future goal split is recorded in `docs/architecture/generic_dse_framework_design_spec_v2.md` §13 and summarized below.

Remaining user-discussion items for the next implementation goal:
- Choose the first multi-candidate architecture families to simulate beyond `balanced-generic-systemc-v0`; at minimum decide whether CPU-only, Host+FPGA minimal, Host+FPGA+CIM, diag-heavy, streaming-heavy, memory-rich, low-power, debug, or future-custom families are in the first budget.
- Define the first real L4 gem5+SystemC descriptor/completion pilot configuration for the QE SCF shell, or explicitly keep L4 as blocked/prototype for the next archive.
- Decide whether top-K finalist evidence defaults to `debug` or `forensic`; the design default is `debug` for finalists and `forensic` for publication/user-selected audit runs.
- Set the SystemC/gem5+SystemC simulation budget per feedback iteration, total promoted samples, and top-K/frontier stability threshold.
- Choose the convergence gate used for “best architecture found”: trusted frontier stability, top-K stability, hypervolume, absolute improvement, uncertainty reduction, family coverage, or budget exhaustion.

Recommended next `/goal` split:
- P0/P1 full-flow evidence goal: close or explicitly block L4 gem5+SystemC descriptor/completion and harden evidence artifacts/claim gating.
- P2/P3 catalog and mapping goal: extend catalog families, validation, DesignPoint generation, legality matrix, seeded beam/local search, and mapping artifact persistence.
- P4/P5 feedback and report goal: implement multi-candidate feedback, convergence/budget reporting, final report generation, and machine-checkable claim validation.
- Validation/archive goal: run build/tests/OpenSpec validation, check protected-path compliance, record limitations, and archive only when every OpenSpec scenario has matching evidence.
