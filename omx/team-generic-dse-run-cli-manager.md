# Generic DSE Team Run CLI Manager

## Target result
Implement the generic DSE design into runnable source so the repo has an auditable end-to-end flow for QE SCF shell timing-level SystemC evidence, gem5+SystemC blocked/prototype reporting when unavailable, architecture catalog extensibility, mapping search with feedback, final reporting, claim validation, and integration tests.

## Preflight summary
- `tmux -V`: available (`tmux 3.4`).
- `$TMUX`: present in the leader shell.
- `omx team --help`: available and returned rc=0.
- Legacy `omx_team -v`: not available on PATH in this environment; use current `omx team` CLI syntax.

## Required lanes and ownership

### Lane 1: P0-L4 gem5+SystemC closure
Owner paths:
- `gem5_integration/`
- `runtime_api/` only if needed and coordinated with leader
- `dse_v2/backends/`
- `model/generic_sim_backend/`

Goal:
- QE SCF shell command/descriptor threads through gem5 GenericAccel or a cleanly handled gem5+SystemC adapter path into SystemC timing execution.
- Produce completion/result evidence.
- Write `gem5.log` when runnable.
- If true gem5+SystemC is unavailable, emit blocked/prototype verdict artifacts and do not claim L4 complete.

### Lane 2: P2 architecture catalog
Owner paths:
- `dse_v2/architecture/` or equivalent catalog package
- `docs/architecture/`
- OpenSpec P2 sections under `openspec/changes/enhance-generic-dse-framework-spec/`

Goal:
- Extensible architecture catalog with multiple families, instances, bindings, and status labels.
- No hardcoded 4-cluster default/only architecture.
- 4-cluster may be represented only as legacy/reference candidate.

### Lane 3: P3/P4 mapping search and feedback optimizer
Owner paths:
- `dse_v2/mapping/`
- `dse_v2/dse/`
- `dse_v2/evidence/` where needed for integration artifacts

Goal:
- Legality matrix, domain-seeded beam/local search, candidate promotion, SystemC sample integration, ranking/surrogate/pruning update, convergence and budget status.

### Lane 4: P5 final report and claim validator
Owner paths:
- `dse_v2/reporting/` or equivalent new module
- `dse_v2/evidence/`
- docs/OpenSpec P5 sections where needed

Goal:
- Final JSON/Markdown report generator.
- Every trusted claim resolves to evidence links.
- Predicted-only/blocked claims cannot appear as winners.

### Lane 5: verification and integration
Owner paths:
- `dse_v2/tests/`
- minimal integration fixes after leader approval

Goal:
- Validate pytest/build/OpenSpec/full-flow commands.
- Detect conflicts, missing evidence, claim-gating violations, protected path modifications.

## Cross-lane constraints
- Obey repo `AGENTS.md` hierarchy.
- Expect dirty tree; do not revert unrelated changes.
- Do not add dependencies or install software.
- Do not rebuild QE datasets.
- Do not modify `/Users/xixilys/project/qe-7.5`.
- Do not modify `soft/qe-7.5/` source for this goal.
- Do not use smoke/fixed-timing/synthetic GEMM as Done evidence; those are bring-up diagnostics only.
- Do not treat L1/L2 analytical/TLM/surrogate prediction as final trusted conclusion.
- Final trusted ranking/winner/Pareto/bottleneck/feasibility claims must cite SystemC or gem5+SystemC evidence.
- If gem5+SystemC cannot truly close, output blocked verdict, blocker list, and next-step checklist; do not claim L4 complete.
- Worker lanes must stay in owned files; shared-file integration belongs to leader.
- Do not skip/xfail/delete tests to hide regression.
- Do not introduce broad formatters/linters or rewrite unrelated generated artifacts.

## Required completion evidence
- End-to-end command exits 0, e.g. `python3 dse_v2/scripts/dse/run_end_to_end_dse.py --workload qe_scf_shell --backend systemc --out runs/dse/<run_id>` or equivalent documented command.
- SystemC path covers QE SCF shell phases: `h_psi`, `s_psi`, `build_H_sub`, `build_S_sub`, `diagonalize/cdiaghg`, `subspace_rotation`, `refresh`, `residual`, `rho_out`, `mix_rho`, `veff`.
- Evidence directory includes manifest/verdict/artifact index, design point, architecture, mapping, workload graph, simulation request/result, phase/resource/data summaries, logs, report artifacts, and claim validation artifacts.
- Mapping artifacts include legality matrix, seed set, candidate/promoted/selected mapping records, simulation samples, and feedback state.
- Report artifacts include trusted ranking, predicted-only section, blocked/prototype section, limitations, replay instructions, and claim-to-evidence links.
- Tests cover full-flow command, evidence existence, claim gating, architecture catalog extensibility, mapping promotion/feedback, and gem5+SystemC blocked verdict.
- Required final commands:
  - `cmake --build model/generic_sim_backend/build -j4`
  - `python3 -m pytest -q dse_v2/tests`
  - `openspec validate enhance-generic-dse-framework-spec --strict --no-color`

## Leader monitoring contract
The leader must monitor `omx team status` until `pending=0`, `in_progress=0`, `failed=0`, or a lane is explicitly blocked with a verdict. Before shutdown, record final team status and integrate only conservative, conflict-free changes.
