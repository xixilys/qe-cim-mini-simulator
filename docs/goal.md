# Adaptive QE-to-FPGA/ASIC DSE Goal

Act as the master control agent for the QE workload-to-FPGA/ASIC implementation DSE project.

The visible execution objective is to coordinate **process-backed Codex/OMX worker capacity** through an adaptive five-slot master/controller with **up to five concurrent worker slots**. The canonical lane families remain `run1`, `run2`, and `run3`, but they are now treated as dynamic work families inside a larger capacity pool rather than as a frozen fixed-slot layout. Slots are capacity, not permanent roles: the controller may launch, monitor, stop, summarize, and reassign them from the current blocker board. The master/controller is not one of the worker slots; it owns dispatch, model routing, status collection, integration order, verification, and claim-boundary review. Primary worker slots are separate OS/tmux-backed `codex exec` processes, not native subagents. Historical `run4`/`run5` artifacts must not be revived as active implementation lanes; any extra capacity is fresh temporary parallelism only.

## Clarified current intent

This goal is the result of the current deep-interview decisions:

- Target status: `deliverable_complete`, not a demo, MVP, or vertical slice.
- Maximum parallelism: **five task-bearing slots total** across primary workers, helper agents, reviewers, verifiers, and probe agents. The controller does not count against the cap while it is only coordinating or integrating.
- Scheduling mode: `full_auto` adaptive scheduling. The controller should decide the next useful parallel work after each handoff, blocker, or verification result instead of freezing all future lane assignments at the start.
- Default write isolation: `lane_local_only` until barrier integration. Workers should avoid shared semantic files unless their prompt explicitly grants that scope and the barrier plan predicts conflicts.
- Primary execution proof: process-backed `codex exec` workers with observable PIDs for implementation lanes; native subagents are allowed for bounded helper work, but they consume a slot and do not prove a primary lane is live.

The document should be read as a living controller contract: it defines the visible total goal, the dispatch loop, the evidence gates, and the stop conditions that prevent false completion.

## Controller mission

Maintain a visible blocker board, dispatch at most five concurrent task-bearing execution units total, collect handoffs, enter barrier integration, verify artifacts, and continue until `Done when` is satisfied or a concrete `Stop if` blocker is recorded.
At every controller turn, report the global objective status, active slot table, barrier state, next dispatch decision, and verification evidence.

The controller's visible status report should be short but mechanically useful:

```text
Global status: deliverable_complete=false | current phase=<preflight|dispatch|monitor|barrier|verification|blocked>
Active slots: N/5 | slot_id -> lane_family, objective, worktree, status, pid/final.md, blocker
Barrier state: <not_entered|collecting|forecasting|integrating_layer|verifying|ready_to_relaunch|blocked>
Next decision: <dispatch|wait|integrate|verify|stop> with one-sentence rationale
Evidence: newest command/artifact paths that justify the state
```

If any line cannot be filled from artifacts, process state, or command output, the controller must classify that field as `unknown` and repair the evidence path before claiming progress.

Liveness invariant: while `deliverable_complete=false`, every controller update must include a five-row scheduler table. If fewer than five task-bearing slots are running or planned, each idle row must be marked `idle_at_barrier` with a concrete reason: `shared_conflict`, `no_independent_blocker`, `waiting_for_tool`, or `unsafe_without_barrier`. A missing idle reason is a controller-contract violation.

## North-star outcome

The global objective is to turn this repository into a research-grade **QE workload -> FPGA/ASIC implementation recommendation DSE system**.

### Goal hierarchy

- **North-star outcome:** a reusable, domain-neutral QE workload -> FPGA/ASIC recommendation DSE system with fail-closed evidence gates and auditable claim boundaries.
- **Current proof path:** DFT/QE full-SCF evaluated-hybrid acceleration, using QE/DFT reference profiles and real-tool evidence where feasible, while preserving domain-neutral core contracts.
- **Per-wave objective:** the controller selects the highest-value independent blockers from the current blocker board, dispatches at most five task-bearing slots, integrates at barrier, and then replans from the updated evidence.

The proof path may narrow the immediate implementation surface, but it must not redefine or downgrade the north-star outcome.

Important scheduling rule: **a shared-semantic barrier on run3 does not justify collapsing the whole wave into one lane**. If run3 is the only shared contract that can safely move, the controller should still fill any remaining capacity with independent read-only, probe-only, blocker-board, or lane-local sidecar work. Idle capacity is acceptable only when the blocker board is truly empty or every remaining task would conflict with an active slot.

Given QE/DFT workload inputs, the system must:

1. ingest workload contracts and workflow facts;
2. analyze workflow / kernel / dataflow structure;
3. search the deployment boundary: what should be offloaded to hardware vs retained on CPU;
4. search architecture / template / mapping / layout / runtime / co-scheduling policies;
5. generate a finite, reproducible release universe and candidate identity scheme;
6. produce separate FPGA and ASIC best / Pareto recommendations;
7. attach evidence level, exact artifacts, blockers, and claim boundaries to every recommendation.

This goal is **not** satisfied by any single vertical slice, including:

- a model-only SystemC projection;
- an h-psi-only or single-kernel proof;
- a fixed hand-picked top-k candidate set;
- a report-only cleanup;
- an IC/EDA availability-only transcript;
- a tool-unavailable placeholder;
- a green test suite that does not map back to candidate × workload × target evidence gates.

Automatic iteration is required until the global objective is either met or blocked by concrete, recorded, mechanically detectable blockers.

### deliverable_complete semantics

`deliverable_complete` is a repository-wide terminal status owned by the master/controller, not by any individual worker slot.
It may be set to `true` only when every `Done when` item is satisfied and every claimed candidate × workflow × target evidence row is present, current, and trusted.
It defaults to `false` if any row is missing, blocked, projection-only, smoke-only, stale, forged, tool-unavailable, or target-inappropriate.
No vertical slice, green test suite, model-only projection, or partial lane completion counts as `deliverable_complete`.

## Operating rules

- `run1`, `run2`, and `run3` remain the canonical implementation families.
- Up to five dynamic task-bearing execution units may be active at once across the whole execution tree when the controller can assign safe independent work.
- If fewer than five slots are active, the controller must state why in the active slot table or blocker board; a smaller wave is a deliberate decision, not the default.
- When any slot finishes, the controller must immediately re-evaluate the blocker board and backfill the freed capacity with the highest-value safe independent task if one exists.
- A wave is not allowed to devolve into a single visible lane merely because the shared `run3` lane is the longest-running one; if other safe work exists, the controller should keep the remaining capacity occupied.
- Dynamic slots are not fixed roles. A completed slot may be reassigned after handoff and blocker / dirty-state checks.
- The master/controller owns dispatch, model routing, integration order, and final claim-boundary review.
- The controller should not pre-freeze all slot assignments at round start. It may revise slot objectives after each handoff or blocker update.
- When one slot finishes early, it should not disturb the other active slots by default: use safe same-lane follow-up, quiet non-disturbing work, or barrier integration as defined below.
- Helper subagents, native subagents, OMX team workers, reviewers, verifiers, and probe agents are auxiliary only, but they still consume one of the five global parallelism slots whenever they perform concurrent scoped task work. They must not be used as evidence that a primary process-backed lane is live unless the required `codex exec` PID evidence exists.
- A tmux pane that only shows a shell prompt, wrapper, or waiting-for-input state is not proof of a live slot; the underlying `codex exec` child process must exist and be observable with `ps`.
- The controller itself is outside the slot cap when it is only coordinating, monitoring, integrating, or doing sequential review.
- Maintain a five-slot scheduler table for every wave: `slot_id`, `lane_family`, `objective`, `worktree`, `writable_scope`, `status`, `pid/final.md`, `handoff_path`, `blocker`, and `next_action`.
- Legal slot statuses are `planned`, `launching`, `running`, `completed`, `blocked`, `lost_before_done`, `terminal_artifacts_incomplete`, `timeout`, and `idle_at_barrier`; any other state is invalid until normalized by the controller.

### Slot counting rules

- Count every live task-bearing unit against the five-slot cap: primary process-backed workers, native helper agents, OMX team workers, reviewers, verifiers, and probe agents.
- Do not count controller-only coordination, sequential barrier review, or deterministic shell commands that are not concurrent task-bearing work.
- A tmux pane by itself does not count as a live task-bearing primary worker; a primary worker counts only when its matching `codex exec` child process exists.
- A slot frees capacity only after a terminal handoff or concrete monitor classification is recorded in the scheduler table.
- A planned slot still counts against dispatch capacity if the controller has committed it for the active wave; stale planned slots must be cancelled or normalized before more work is launched.

## Required controller flow

### Phase 0 — adaptive preflight

Before launching or resuming implementation work, create a preflight checkpoint under `.omx/context/adaptive-five-slot-preflight-<timestamp>.md` and keep it current. The checkpoint must record:

1. Current git / worktree state for:
   - the main repository root;
   - the integration worktree, if present;
   - `/mnt/f/phd/year_2/project/dft_accelerate.omx-worktrees/launch-run1`;
   - `/mnt/f/phd/year_2/project/dft_accelerate.omx-worktrees/launch-run2`;
   - `/mnt/f/phd/year_2/project/dft_accelerate.omx-worktrees/launch-run3`.
2. The exact team plan for each active slot:
   - slot number and current lane-family / blocker-board assignment;
   - lane objective;
   - team roles;
   - writable file scope;
   - expected artifacts and handoff path;
   - targeted tests / commands;
   - likely conflict hotspots with the other active slots;
   - stop / blocker conditions.
3. The exact model-routing plan:
   - model name;
   - reasoning effort;
   - launch command or runtime config;
   - environment variables that could accidentally force `xhigh`;
   - proof that worker lanes will not inherit a blanket `xhigh` setting.
4. A dry-run or smoke-debug record proving the launch and completion-detection scheme works before real work starts:
   - at least one harmless shell / status command per active slot;
   - `ps` / tmux evidence showing the intended slot sessions, model efforts, and a live child PID for each slot;
   - terminal evidence proving `wrapper.done`, worker return code, `turn.completed`, final handoff output, absent tmux session after completion, and absent `codex exec` PID after completion;
   - confirmation that no worker slot is accidentally launched with `model_reasoning_effort="xhigh"`;
   - confirmation that master/integration remains responsible for final high-risk review.
5. A Superpowers / skills workflow record:
   - which skills were loaded before planning or implementation;
   - which skills apply to each active slot;
   - how the skill instructions are represented in the worker prompt or team inbox;
   - which skill-gated steps must happen before code edits, tests, completion claims, or handoff.

If the preflight cannot prove the slot / team / model configuration, stop and repair the launch plan before editing repository code.

## Worker launcher and completion monitor contract

Use the local Codex configuration as the authority for model / provider selection. Worker launch commands should not hard-code stale model names by default. Override only the per-slot `model_reasoning_effort` unless a task has a recorded reason to override model / provider.

Reusable local launch / monitor surfaces:

- launcher: `.omx/context/adaptive_codex_worker_launcher.sh`
- monitor: `.omx/context/adaptive_codex_worker_monitor.sh`

Canonical launch shape:

```bash
env -u OMX_TEAM_WORKER_LAUNCH_ARGS CODEX_CI=1 \
  codex exec --json --sandbox workspace-write -C "$WORKTREE" \
  -c "model_reasoning_effort=\"$EFFORT\"" \
  -o "$RUN_DIR/final.md" - < "$RUN_DIR/prompt.md" \
  > "$RUN_DIR/events.jsonl" 2> "$RUN_DIR/stderr.log"
```

Rules:

- Always unset `OMX_TEAM_WORKER_LAUNCH_ARGS` for worker launches unless the preflight deliberately proves it is safe. The current master environment may contain stale `model_reasoning_effort="xhigh"` launch args.
- Do not pass `--ask-for-approval` or `-a` to `codex exec`; local Codex 0.133 rejects those flags under `exec`.
- Feed prompts through stdin from a prompt file. Do not count prompt text pasted into a pane as a launch.
- Liveness proof requires both a tmux pane and a live `codex exec` process whose command includes the slot's `final.md` path and the expected `model_reasoning_effort`.
- The launcher emits evidence surfaces (`wrapper.start`, `events.jsonl`, `stderr.log`, `final.md`, `wrapper.done`, and the printed liveness check); it does **not** by itself prove the launch is healthy.
- The monitor is a local polling/classification tool. It checks `wrapper.done`, worker return code, `turn.completed`, nonempty `final.md`, absent tmux session after completion, and absent matching `codex exec` PID after completion. It does **not** perform barrier integration and does **not** enforce model-effort policy beyond matching the run directory / `final.md` process.
- The controller/preflight is responsible for proving the expected `model_reasoning_effort`, slot count, skill workflow, and barrier readiness from the launcher / monitor artifacts plus `ps` / tmux evidence.
- Completion proof requires `wrapper.done`, `rc=0` or a recorded nonzero blocker, `events.jsonl` containing `turn.completed`, a nonempty `final.md`, the tmux session absent after completion, and no matching `codex exec` PID after completion.
- The monitor should classify a slot as `completed`, `nonzero-return-blocker`, `lost_before_done`, `terminal_artifacts_incomplete`, or `timeout`; do not leave a slot silently idle.
- `terminal_artifacts_incomplete` means the wrapper reached a terminal state but required proof artifacts are missing, stale, or contradictory; treat it as a blocker requiring controller repair before relaunch.
- Nonzero worker exits are blocker handoffs, not `completed` states.

Default effort policy:

- controller / barrier integration / final adversarial audit: `xhigh`;
- implementation / semantic repair / contract design: `high`;
- evidence indexing / reporting / verification sweeps: `medium`;
- shell / status / probe / read-only monitors: `low` or no model.

## Human-readable implementation roadmap

The practical route to `deliverable_complete` is not one giant run. It is a repeated five-slot controller loop over these milestones:

1. **P0 — orchestration sanity:** prove launcher / monitor / completion detection, no accidental blanket `xhigh`, no prompt-only panes counted as live work, and no unclassified worker exits.
2. **P1 — preservation and barrier integration:** preserve dirty main and worker trees, import additive lane outputs, forecast conflicts, then integrate exactly one semantic layer at a time with targeted tests.
3. **P2 — search universe closure (`run1` family):** close candidate identity, deployment-boundary search, architecture / mapping / runtime policy search, finite release universe, pruning rationale, and stable provenance.
4. **P3 — full-SCF evaluated-hybrid closure (`run3` family):** close descriptor / runtime scheduling, host/device partitioning, transfer/sync costs, CPU-retained stage accounting, Step5 replay, and final-report consumers.
5. **P4 — evidence and claim-gate closure (`run2` family):** close QE baselines, per-kernel correctness, HLS/RTL/Vivado/DC/gem5/SystemC evidence, fail-closed ledgers, and target-specific FPGA vs ASIC claim boundaries.
6. **P5 — final adversarial release audit:** verify prompt-to-artifact checklist, requirement-evidence matrix, artifact hashes, blocker report, and explicit status classification. Only this phase can set `deliverable_complete=true`, and only if every hard gate below is backed by fresh evidence.

At any milestone, the controller may use fewer than five slots. It should use all five only when the blocker board contains five independent, safe, well-scoped tasks with disjoint write scopes or read-only/probe scopes. Idle capacity is preferable to creating merge conflicts or unverified false progress.

## Adaptive replanning algorithm

After each handoff, blocker, or verification result, recompute the next work instead of continuing a stale fixed plan:

1. Update the blocker board from artifacts, tests, worker handoffs, and process monitor output.
2. Mark each item as `lane_local`, `shared_semantic`, `verification_only`, `probe_only`, or `blocked_external`.
3. Dispatch immediately only items that are independent of active slots and have a worker-local `Objective / Scope / Constraints / Done when / Stop if` contract.
4. Hold shared semantic changes for barrier integration unless no other active slot can conflict with them.
5. Prefer same-lane follow-up for a slot that finished early; otherwise assign quiet read-only audit/provenance work or mark it `idle_at_barrier`.
6. Refill any freed capacity before accepting a one-lane wave, unless the blocker board is truly empty or every remaining task conflicts with an active slot.
7. Never exceed five concurrent task-bearing units, including native helper agents and OMX team workers.
8. Re-enter barrier before any merge, rebase, cherry-pick, final-report semantics change, evidence-gate change, or `deliverable_complete` claim.

## Scheduling and phase plan

The controller should use a rolling loop, not a one-shot fixed assignment. The active wave is chosen from the blocker board, and the next wave is selected only after the current wave yields a handoff or blocker classification.

### Round 0 — preflight refresh

Before each execution wave:

1. Refresh the adaptive dispatch preflight.
2. Verify worktree cleanliness or preservation state.
3. Verify each active slot's team plan, model routing, and skill workflow.
4. Smoke-check the launch configuration.
5. Record the planned round under `.omx/context/adaptive-five-slot-round-<timestamp>.md`.

### Round 1 — parallel dispatch

Dispatch the highest-value independent blockers concurrently with explicit prompts / inboxes. The default first wave usually maps to the canonical lane families, but the controller may choose any safe independent partition from the blocker board.

Typical lane-family mapping:

- `run1`: release universe, candidate identity, search-control, provenance.
- `run2`: real evidence, QE / toolchain / IC-EDA attempts, claim gating.
- `run3`: full-SCF evaluated-hybrid accounting, runtime / descriptor, reporting.

Adaptive slots 4 / 5, and any freed slot, must be considered for safe sidecar work before being left idle. Legal sidecars are read-only audits, probe-only tool checks, lane-local verification, conflict forecasts, artifact hash/provenance summaries, prompt-to-artifact matrices, monitor/liveness checks, or `.omx/context`-only blocker-board updates. They must not edit shared source/report/evidence contracts while a shared semantic barrier is active.
When run3 is the current shared-semantic mainline, the controller should preferentially keep remaining slots busy with safe sidecar work rather than waiting for run3 alone to finish. Freed slots must be considered for read-only, probe-only, or lane-local follow-up before being left idle.

Each prompt must include:

- lane objective;
- writable scope;
- expected handoff;
- tests / commands;
- model effort;
- skill workflow.

Each worker prompt must include a worker-local contract with exactly these headings: `Objective`, `Scope`, `Constraints`, `Done when`, and `Stop if`.

The controller should not micromanage normal worker steps after dispatch.

#### Worker prompt template

Every implementation, verification, probe, or helper prompt must fill this template with concrete content before launch:

```markdown
Objective
- One sentence that names the blocker or artifact this slot owns.

Scope
- Writable files/directories or explicit read-only/probe scope.
- Out-of-scope shared files and conflict hotspots.

Constraints
- Skill workflow to load first.
- Model effort and sandbox.
- No destructive merge/rebase/cherry-pick; do not revert unrelated dirty changes.
- Claim-boundary and fail-closed rules relevant to the slice.

Done when
- Exact handoff path.
- Exact artifacts/files expected.
- Exact tests/commands to run or concrete blocker evidence if they cannot run.

Stop if
- Mechanically detectable blockers, including shared-semantic conflict, missing authority, tool unavailability, failing regression, model-effort mismatch, or missing skill gate.
```

A prompt that leaves any of these headings vague is a launch blocker, not a worker discretion point.

### Round 2 — low-noise monitoring

While runs are active, the controller performs periodic read-only checks only:

- tmux / OMX / process liveness;
- completion monitor state (`completed`, `nonzero-return-blocker`, `lost_before_done`, `terminal_artifacts_incomplete`, or `timeout`);
- current task status;
- terminal outputs or blockers;
- unexpected `xhigh` inheritance;
- missing skill-workflow evidence;
- dirty / uncommitted state risks.

Do not interrupt a healthy working lane just to ask for status. Intervene only for blocker, runaway scope, wrong model, missing skill gate, destructive action risk, or claim-boundary violation.

### Round 3 — handling early completion

When one slot finishes before the others, first collect a terminal handoff:

- commit or no-code artifact reference;
- files changed;
- tests / commands run with outcomes;
- blockers and claim boundaries;
- suggested next action;
- merge / integration risks.

#### Reassignment protocol

A slot may be reassigned only after the controller records a terminal handoff or concrete monitor classification for the previous assignment.
Before relaunch, the new objective must be written to the blocker board and scheduler table with fresh `Objective / Scope / Constraints / Done when / Stop if` content.
The reassigned work must be lane-local or read-only unless the controller has entered barrier integration and recorded the shared-contract merge plan.
Any task that changes candidate identity, evidence-gate semantics, final-report semantics, or release-universe contracts waits for barrier integration.

Then classify the next action:

#### A. Safe same-lane follow-up: continue immediately

Continue assigning work to the completed slot if the follow-up:

- stays inside that slot's existing scope;
- does not depend on unfinished results from other slots;
- does not change shared report / search / evidence semantics;
- does not touch known conflict hotspots;
- can produce a separate handoff and targeted verification.

Examples: add missing lane-local regression coverage, improve handoff clarity, run lane-local tests, repair lane-local artifact indexing, or prepare a merge forecast.

#### B. Quiet non-disturbing work: continue without implementation risk

If implementation follow-up is risky but useful work remains, assign quiet work:

- read-only audit of the slot's own output;
- `.omx/context` handoff cleanup;
- blocker matrix update;
- test transcript collation;
- artifact hash / provenance summary;
- conflict forecast preparation.

This work must not edit shared source contracts unless explicitly deferred to the barrier.

#### C. Shared semantic or integration work: wait for barrier

Do not assign new implementation work if the next step would:

- modify shared final-report / search / evidence contracts;
- alter candidate identity or evidence-gate semantics used by another active slot;
- require another slot's unfinished output;
- merge / cherry-pick / rebase active worktrees;
- change global claim boundaries.

Mark the slot idle / terminal with its handoff and wait for barrier integration.

### Round 4 — barrier integration

Enter barrier integration when:

- all required active slots for the wave have terminal handoffs or concrete monitor-classified blockers;
- any slot reports a blocker that changes the plan for the others;
- a shared contract / merge is needed before useful work can continue;
- model / skill / preflight violations are found;
- the master needs to adjudicate claim boundaries before further work.

At the barrier, the master must run this loop before any new shared-semantic implementation dispatch. This does not block safe sidecar work that is read-only, probe-only, lane-local verification, monitor/liveness, artifact inventory, or `.omx/context`-only reporting.

Barrier loop: `collect -> classify -> conflict forecast -> integrate one layer -> verify -> update blocker board -> decide relaunch-or-stop`.
The controller must not dispatch the next implementation wave until the current barrier has recorded merge order, verification commands/results, unresolved blockers, and the next per-slot `Objective` / `Scope` / `Constraints` / `Done when` / `Stop if` contracts.
A barrier on `run3` means only the shared semantic integration lane is serialized. It does not collapse the whole wave to one active lane. The controller must fill remaining capacity with safe sidecar/probe/read-only work unless it records a per-slot idle reason.

#### Barrier authority

The latest barrier record under `.omx/context/adaptive-five-slot-barrier-<timestamp>.md` is the source of truth for the next wave.
Worker handoffs, stale preflight plans, and older round files are advisory after a newer barrier exists.
No slot may claim global completion from its own handoff alone.
Only the controller may change global status, merge order, shared semantic contracts, or `deliverable_complete`.
If barrier artifacts disagree, the controller must record the conflict, choose the authoritative artifact with rationale, and keep `deliverable_complete=false` until the conflict is resolved and verified.

The detailed barrier actions are:

1. Compare slot handoffs against the global objective.
2. Produce or update a conflict forecast.
3. Choose and record merge order.
4. Integrate one layer at a time.
5. Run targeted tests after each layer.
6. Update `.omx/context` with changed assumptions, blockers, and next assignments.
7. Start the next round if `Done when` is not satisfied.

Default merge order:

1. `run1` first, because search universe / candidate identity / provenance constrain downstream reports.
2. `run3` second, because full-SCF accounting / runtime / report consumers bind the recommendation surface.
3. `run2` last, because real evidence / toolchain / claim-gating should land against the final report and search contracts.

The master may change this order only with recorded evidence and rationale.

### Round 5 — automatic continuation

After every barrier, if the global `Done when` items are not satisfied:

1. Identify the highest-value blockers or missing artifacts.
2. Split them into independent canonical lane-family tasks plus optional adaptive-slot tasks.
3. Reconfirm model and skill routing.
4. Relaunch or resume up to five active task-bearing units, using process-backed `codex exec` slots for primary worker work.
5. Continue the loop.

Next-wave selection must rank tasks by: unblock shared contracts first, then highest evidence-gap risk, then lane-local regression coverage, then quiet audit/provenance work. A slot may be relaunched only when its new task is independent of active slots or explicitly waits at barrier for shared-contract changes.

Do not stop merely because one round produced green tests or useful artifacts. Stop only when the `Done when` list is satisfied, a user cancels, or a concrete blocker prevents meaningful progress.

## Superpowers and skill workflow policy

The adaptive orchestration must follow the local Superpowers skill discipline in addition to this repository goal. Before the master or any slot worker performs planning, implementation, debugging, verification, review, or documentation changes, it must check whether a skill applies and load the current `SKILL.md` for that skill.

Required baseline process:

1. Load `using-superpowers` first for each new master session, slot worker session, team worker prompt, or tasked child-agent prompt. The only allowed exception is a pure read-only metadata probe whose prompt explicitly states that no planning, coding, debugging, verification, or completion claim will occur.
2. For creative planning, behavior changes, new feature design, or goal refinement, load the applicable planning / design skill before editing. If the skill requires a design or approval gate, represent that gate explicitly in the run plan or explain why a higher-priority AGENTS / user instruction narrows it.
3. For implementation or bugfix work, load the relevant development / testing skill before edits. At minimum, include a test / verification plan in the run handoff.
4. For completion claims, load and follow `verification-before-completion` or the equivalent local verification rule before reporting success.
5. In Codex / OMX environments where there is no separate Skill tool, opening the listed local `SKILL.md` file is the accepted adaptation. Do not rely on memory of a skill.

Every slot prompt / team inbox must include a short "Skill workflow" block naming the skills to load first. The master preflight must verify this block exists before launching the worker. Missing skill workflow instructions are a launch blocker, not a post-hoc cleanup item.

For spawned helper agents outside the primary worker slots, the default policy for this goal is:

- they must also follow the Superpowers workflow;
- they must auto-select applicable skills from the task type and load them before doing work;
- they must use the lane objective to choose the relevant skill(s) themselves instead of waiting for the master to spell out every coding / debugging step;
- they must not rely on memory of a previous session’s skill state;
- they must record the loaded skills in their first progress note or handoff;
- they must not start coding, debugging, or claiming completion without the relevant skill gate.

Task-type skill mapping:

- **Planning / goal refinement / coordination** -> `using-superpowers` first, then `brainstorming`, `goal-prompt-builder`, `plan`, or `writing-plans` as appropriate.
- **Implementation / refactor / feature work** -> `using-superpowers` first, then `tdd` or `test-driven-development`, plus any repo-local implementation skill that matches the slice.
- **Debugging / failure analysis** -> `using-superpowers` first, then `diagnose`, `systematic-debugging`, or a task-specific debugger skill before editing.
- **Verification / completion claim** -> `using-superpowers` first, then `verification-before-completion`, `code-review`, `requesting-code-review`, or `ultraqa` as appropriate.
- **Read-only exploration / evidence gathering** -> `using-superpowers` first, then `analyze`, `explore`, `researcher`, or shell-only probe instructions as appropriate.

For this goal, do not treat the `SUBAGENT-STOP` note inside `using-superpowers` as a reason to skip the workflow for tasked child agents. If a child agent is executing a scoped task for this goal, it still needs to load and follow the relevant skills before acting.

## Scope

In scope:

- `dse_v2`
- `docs/architecture`
- `docs/benchmarks`
- `model/generic_sim_backend`
- `gem5_integration`
- `runtime_api`
- `tools` and scripts needed for QE workflow parsing, search-space generation, evidence adjudication, FPGA / ASIC / IC-EDA probing, final reporting, and OMX coordination artifacts under `.omx/context`
- run worktrees `launch-run1`, `launch-run2`, and `launch-run3`

Out of scope unless explicitly re-approved:

- reviving historical `run4` / `run5` artifacts as active implementation lanes;
- broad rewrites of unrelated historical application-specific material;
- generated caches, simulator builds, gem5 `m5out`, scratch `tmp*` outputs, or local credentials.

## Canonical lane-family intent

### `run1` — release universe and search-control lane

Default lane objective: make the finite release universe, candidate identity, deployment-boundary search, architecture / template parameters, mapping / layout policies, pruning rationale, and Step2 / Step3 eligibility provenance reproducible and fail-closed.

Default team plan:

- Run lead: implementation owner for search-space and candidate identity contracts.
- Optional reviewer / verifier: read-only or targeted-test role for provenance, hash, and fail-closed regressions.
- Model policy: `high` for implementation; `medium` or shell-only for status / probe / report extraction; never default `xhigh`.
- Skill workflow: load `using-superpowers`, then planning / design or TDD / verification skills that match the selected code slice before editing.
- Execution proof: the slot is only considered live if the expected `codex exec` child PID exists; a prompt-only pane is idle / terminal, not running.

Expected outputs:

- search-space / candidate-generation artifacts with stable IDs and provenance;
- tests proving no fixed top-k / fixed manual candidate set can masquerade as the release universe;
- handoff note under `.omx/context/run1-*.md` with files changed, tests run, blockers, and merge risks.

### `run2` — real evidence and toolchain lane

Default lane objective: make QE baseline / accelerated evidence, FPGA / Vivado evidence, ASIC / DC evidence, IC / EDA availability attempts, and claimable-vs-blocked evidence classification visible without upgrading unavailable or projection-only evidence into trusted PPA claims.

Default team plan:

- Run lead: evidence pipeline and report integration owner.
- Optional toolchain / probe worker: shell-heavy probe role for QE / gem5 / Vivado / DC / VCS availability and exact command transcripts.
- Optional verifier: fail-closed test role for forged, missing, smoke-only, or tool-unavailable evidence.
- Model policy: `high` for evidence / report implementation; `medium` for transcript summarization and artifact indexing; shell-only for command probes; never default `xhigh`.
- Skill workflow: load `using-superpowers`, then debugging / diagnosis, test-driven, and verification skills as appropriate; shell-only probes still need a recorded verification and blocker protocol.
- Execution proof: if the pane is only parked at an input prompt with no live child PID, classify it as idle or terminal rather than as an active evidence lane.

Expected outputs:

- exact tool-attempt transcripts and availability artifacts;
- evidence ledger rows classified as `trusted_pass`, `trusted_fail`, `blocked_tool_unavailable`, `blocked_missing_input`, `blocked_invalid_evidence`, or `projection_only_not_claimable`;
- handoff note under `.omx/context/run2-*.md` with claim boundaries and unclaimable gaps.

### `run3` — full-SCF evaluated-hybrid/runtime/reporting lane

Default lane objective: make the full-SCF evaluated-hybrid path report host / device partitioning, descriptor / runtime scheduling, transfer / sync costs, CPU-retained stages, workflow coverage, Step5 replay, and final report / adjudication completeness.

Default team plan:

- Run lead: full-SCF accounting, runtime / descriptor, and final-report completeness owner.
- Optional test worker: targeted regression owner for end-to-end accounting and blocked / projection-only status propagation.
- Optional documentation / audit worker: update runbook / claim-boundary text only after code / report contracts are verified.
- Model policy: `high` for implementation and regression design; `medium` for docs / report reconciliation; shell-only for deterministic validation commands; never default `xhigh`.
- Skill workflow: load `using-superpowers`, then planning / design, TDD, documentation, and verification skills that match the slice before editing or reporting completion.
- Execution proof: prompt-only or wrapper-only panes do not count as an active slot; the lane must have a live `codex exec` child before any running claim.

Expected outputs:

- full-SCF evaluated-hybrid accounting artifacts that include host-bound stage costs and do not count CPU-retained work as hardware acceleration benefit;
- Step5 / final-report evidence that remains fail-closed when source-flow maps, descriptor bundles, runtime records, or tool evidence are incomplete;
- handoff note under `.omx/context/run3-*.md` with tests, blockers, and integration risks.

## Model and runtime routing policy

- Master / controller may use `xhigh` only for integration, conflict resolution, architecture-level decisions, and final adversarial audit.
- Ordinary worker slots must not be launched with blanket `xhigh`.
- Local Codex configuration is the authority for model / provider selection unless a launch checkpoint records a task-specific override. Worker launches should normally override only `model_reasoning_effort`.
- Default worker policy:
  - implementation and regression design: local model / provider with `high`;
  - report extraction, status summarization, documentation reconciliation, and narrow artifact indexing: local model / provider with `medium`;
  - simple file / symbol lookup: normal Codex repository inspection, shell read-only probes, or low-effort worker;
  - deterministic shell / test / probe loops: shell / OMX runtime with no model when feasible.
- Before every team or slot launch, explicitly inspect and override any stale `OMX_TEAM_WORKER_LAUNCH_ARGS`, inherited `--model`, or `model_reasoning_effort="xhigh"` setting that would make all workers `xhigh`.
- Record the final launch command / config for each active slot in `.omx/context`, then verify the live processes with `ps`, tmux pane metadata, or OMX status output.
- If a worker needs higher reasoning for a narrow decision, escalate that one decision to master or a bounded reviewer; do not relaunch the whole run as `xhigh`.

## System constraints

- The final system goal is: QE workload input -> workflow / kernel / dataflow analysis -> deployment-boundary + architecture + mapping + memory-layout + runtime / co-scheduling DSE -> best FPGA implementation recommendation + best ASIC implementation recommendation.
- "What to deploy to hardware" is part of the search space. Do not pre-fix acceleration to full-SCF, FFT, H-psi, projector, or any specific kernel subset.
- The current proof path is DFT/QE full-SCF hardware DSE with a DFT reference profile/schema while keeping reusable core IR/control-plane contracts domain-neutral.
- The first prototype target is full-SCF evaluated-hybrid, not full-SCF device-resident; CPU-retained I/O, SCF control, convergence, diagonalization, mixing, transfer, and synchronization costs must remain in end-to-end timing/energy accounting.
- Hardware acceleration claims are limited to gated FFT, transpose, Hψ, projector, reduction, and DMA paths unless any additional stage passes the same correctness, simulation/synthesis, FPGA/ASIC-specific evidence gates.
- Release-complete DFT/QE proof requires the six representative SCF workload classes, each with descriptor-plus-runnable-bundle inputs, baseline commands, oracles/tolerances, and candidate × target evidence rows.
- For every major SCF kernel claimed as accelerated, evidence must include golden correctness plus HLS C-sim or RTL simulation, HLS C-synthesis or RTL synthesis, and then Vivado implementation for FPGA claims / DC timing-area-power for ASIC claims.
- Step boundary contract: Step1 records workload facts only; Step2 owns architecture/deployment-boundary/candidate generation and screening; Step3 records raw execution results; Step4 adjudicates evidence/calibration/claims; Step5 assembles replay/report artifacts.
- CIM / near-memory is only one searchable architecture template / module inside the architecture search space, not a separate headline conclusion.
- Search candidate identity must include deployment boundary, host / device partitioning, accelerated / CPU-retained sets, architecture / template parameters, mapping, memory layout, runtime / co-scheduling policy, descriptor granularity, fallback policy, and target platform.
- Maintain a frozen finite release universe for each release claim: workload suite, candidate universe, pruning / legality rationale, and candidate × workflow × deployment-boundary × evidence-gate matrix.
- Use real measurement when feasible. FPGA claims require FPGA / HLS / RTL / Vivado evidence; ASIC claims require RTL / DC / timing / area evidence. DC-only cannot prove FPGA claims; Vivado-only cannot prove ASIC claims.
- SystemC / gem5 / QE / IC-EDA evidence must be used to calibrate, compare, and adjudicate search results; model-only results are projection-only.
- Missing, unavailable, blocked, smoke-only, projection-only, or forged evidence must fail closed and must never be counted as trusted pass.
- Keep the core DSE control plane domain-neutral. QE-specific facts belong in profiles, importers, adapters, reference workloads, or fixtures.
- Expect dirty worktrees. Do not revert unrelated user changes. Preserve worker work before merge / rebase. Avoid committing generated caches, simulator builds, gem5 `m5out`, or scratch `tmp*` outputs.
- The plan must stay living: after each meaningful run result, blocker, test failure, evidence result, launch-config change, or merge, update `.omx/context` with the revised plan, changed assumptions, next assignments, and claim-boundary impact.
- Superpowers / skill workflow is part of the run contract. Do not let workers skip applicable skills because a task looks simple or because a similar skill was read in an earlier session.
- Do not claim deliverable-complete unless every `Done when` item below is backed by fresh artifacts and verification evidence.

## Current active checkpoint

Current barrier authority is `.omx/context/adaptive-five-slot-barrier-20260527T022930Z-adaptive-five-slot-wave-20260527T022040Z-terminal-handoff.md`.

Current semantic order:
1. Earlier run1/run2/run3 semantic layers remain historical progress only; they do not prove `deliverable_complete`.
2. Barrier `.omx/context/adaptive-five-slot-barrier-20260526T225009Z-qe-baseline-ledger-attachment-20260527T065745+0800.md` integrated `candidate_workflow_evidence_ledger_qe_baseline_materialization_attachment` into `dse_v2/reporting/complete_dse_claims.py` and its focused regression while preserving all completion-upgrade flags as false.
3. Wave `.omx/context/adaptive-five-slot-round-20260526T225009Z.md` completed five process-backed read-only/probe sidecars; the controller must use their handoffs only as blocker-board input, not completion evidence.
4. Wave `.omx/context/adaptive-five-slot-round-20260526T231353Z.md` completed one run3 report-propagation implementation slot plus read-only/probe sidecars and refill sidecars under `.omx/context/adaptive-five-slot-refill-20260526T232939Z-round.md`.
5. The latest barrier integrated only the run3 QE baseline / full-SCF row-accounting attachment visibility layer into `dse_v2/reporting/final_report.py`, `dse_v2/reporting/complete_dse_claims.py`, and their focused reporting tests. It did not wholesale copy the run3 worktree because conflict forecast showed large overlap with dirty main-repo semantic layers.
6. Barrier `.omx/context/adaptive-five-slot-barrier-20260527T000123Z-run3-negative-raw-completion-leak-test.md` integrated the negative raw-completion leak regression in `dse_v2/tests/test_final_report_validation.py` and `dse_v2/tests/test_complete_dse_reporting_claims.py`, proving raw optimistic `deliverable_complete=true` source payloads remain non-upgrading in the final report and requirement-matrix consumer surfaces.
7. Barrier `.omx/context/adaptive-five-slot-barrier-20260527T002248Z-run2-target-stale-source-ref-regression.md` integrated a test-only target-input trust regression in `dse_v2/tests/test_dft_hardware_deployment_target_selection.py`, proving declared-but-missing or declared-but-hash-mismatched raw target source refs fail closed with `fpga_target_catalog_missing_trusted_raw_source_refs` and `asic_target_library_probe_missing_trusted_raw_source_refs` while all recommendation / completion upgrade fields remain false.
8. Reassignment/backfill decisions after any early slot completion must prefer main-repository `.omx/context` evidence for global artifacts; lane worktrees may not contain the latest controller context.
9. Wave `.omx/context/adaptive-five-slot-wave-20260527T002636Z-preflight.md` launched five process-backed workers and rolling refill sidecars. The liveness record proved five distinct `codex exec` final targets at launch, but all current-wave workers are now terminal; the stale `5/5 running` status has been superseded by barrier `.omx/context/adaptive-five-slot-barrier-20260527T004713Z-wave-002636-terminal-handoff.md`.
10. Wave `.omx/context/adaptive-five-slot-wave-20260527T010749Z-preflight.md` relaunched five process-backed worker slots from barrier `.omx/context/adaptive-five-slot-barrier-20260527T010350Z-wave-004908-terminal-handoff.md`; launch liveness is recorded at `.omx/context/adaptive-five-slot-wave-20260527T010749Z-liveness-after-launch.md`, refill/idle reasoning at `.omx/context/adaptive-five-slot-wave-20260527T010749Z-refill-decision-20260527T012503Z.md`, and terminal handoff at `.omx/context/adaptive-five-slot-barrier-20260527T012945Z-adaptive-five-slot-wave-20260527T010749Z-terminal-handoff.md`.
11. The 20260527T010749Z wave was intentionally substantive, not a keepalive-only fill: slot1 mapped release crosswalk feasibility and found no trusted `dft-*::map_*` -> `cdse_*` bridge, slot2 produced the target JSON producer/test plan, slot3 performed gem5 dry-run preflight, slot4 added the full-SCF proxy-runtime fail-closed regression, and slot5 audited controller liveness/status drift. All five slots have terminal `monitor.summary` records.
12. Wave `.omx/context/adaptive-five-slot-wave-20260527T013502Z-preflight.md` launched five process-backed workers and dynamic refills. Terminal handoff / integration authority is `.omx/context/adaptive-five-slot-barrier-20260527T020432Z-adaptive-five-slot-wave-20260527T013502Z-terminal-handoff.md`.
13. The 20260527T013502Z wave integrated three semantic layers into the main repository: slot1 summary-side frozen-release candidate ID guardrail, slot2 raw-ref target input JSON producer, and slot3 full-SCF proxy-proof metadata guardrail. Barrier backups live under `.omx/context/barrier-backups/20260527T020451Z-slot1-before`, `.omx/context/barrier-backups/20260527T020750Z-slot2-before`, and `.omx/context/barrier-backups/20260527T020824Z-slot3-before`.
14. Barrier verification for the integrated 20260527T013502Z layers passed: `python3 -m pytest -q dse_v2/tests/test_dft_deployment_decision_summary.py dse_v2/tests/test_complete_dse_done_when_4_6_audit.py dse_v2/tests/test_dft_target_input_json_producer.py dse_v2/tests/test_dft_hardware_deployment_target_selection.py dse_v2/tests/test_dft_full_scf_accounting.py dse_v2/tests/test_dft_full_scf_end_to_end_comparison.py` -> `66 passed in 130.89s`. This is integration evidence only, not `deliverable_complete`.
15. Wave `.omx/context/adaptive-five-slot-wave-20260527T022040Z-preflight.md` launched five process-backed read-only/probe sidecars after the 013502Z integration barrier. Terminal handoff / blocker-board synthesis authority is `.omx/context/adaptive-five-slot-barrier-20260527T022930Z-adaptive-five-slot-wave-20260527T022040Z-terminal-handoff.md`.
16. The 20260527T022040Z sidecars refreshed the blocker board without source edits: release-package summary binding remains the next run1 action, trusted FPGA/ASIC raw target sources are still absent, gem5/L4 remains blocked by missing `swig`/`gem5.opt`, no trusted full-SCF runtime/numerical seed pair exists, and the 013502Z integrated file hashes match worker worktrees.
17. The next controller action is `barrier/ready_to_relaunch`: choose a new set of at most five substantive independent slots from the refreshed blocker board, rather than counting drained workers or fake keepalives as active capacity.

Current hard-gate status:

- SystemC backend build/ctest: `proven_current`.
- QE SCF SystemC/model-level full-flow pilot: `proven_current_model_level`.
- IC/EDA tool availability: `partially_proven_tool_access` through prior SSH `ic-eda` for dc_shell, VCS, and Vivado; the 20260527T022040Z read-only worker sandbox could not open the SSH socket, so controller-level or non-read-only IC/EDA probing is the next required evidence step. This is not design PPA closure.
- Report-consumer fail-closed regression against raw optimistic row-accounting payloads: `proven_current_non_upgrading`.
- Target-input trust fail-closed regression against declared-but-untrusted raw source refs: `proven_current_non_upgrading`.
- Full-SCF proxy-materialized runtime trace fail-closed regression: `proven_current_non_upgrading` through `test_full_scf_row_materializer_blocks_proxy_materialized_runtime_trace` plus the 20260527T013502Z proxy-proof metadata guardrail; this is a guardrail only and not trusted full-SCF evidence.
- Release-package candidate identity provenance: `blocked_fail_closed` because deployment summaries now bind reported IDs to the frozen `complete_dse_qe_release_v1` legal `cdse_*` universe and block out-of-universe IDs with `deployment_summary_candidate_ids_not_in_frozen_release_universe`; the next safe probe is to bind a real deployment decision summary into the release-package path and observe the fail-closed/pass status without crosswalking IDs.
- Release crosswalk repair evidence: `blocked_no_crosswalk`; slot1 scanned the current artifacts and found no artifact-backed `dft-*::map_*` -> `cdse_*` bridge, so direct renaming remains unsafe.
- gem5 GenericAccel/L4: `blocked_missing_build_dependency`; clone-local graft/preflight exists, but `swig` is missing, no `gem5.opt` exists, and no descriptor/request/microarchitecture/completion runtime proof has been produced.
- Controller liveness for wave 20260527T022040Z: `proven_terminal`; all five read-only/probe sidecars have terminal `monitor.summary` files with `status=completed`, and current process sampling after monitor completion found zero live matching `codex exec` workers.
- Target input JSON producer contract: `proven_current_non_upgrading`; it emits target JSONs only from separate SHA-256-backed raw refs and fails closed for missing/stale/self-referential/placeholder/Vivado-part-support-only sources. The 20260527T022040Z probe found no complete trusted target catalog/probe source yet.
- Target-specific FPGA/ASIC evidence ledger: `blocked_missing_input` until candidate/workflow/deployment/target rows, selected FPGA/ASIC model bindings, and target-specific Vivado/DC evidence are present.
- QE baseline/value evidence: current pure-software baseline materialization and QE baseline / full-SCF row-accounting attachment may be surfaced as non-upgrading traceability only; they are not hardware/PPA evidence.
- gem5/L4: source root exists at `gem5_integration/gem5` and GenericAccel has been grafted clone-locally under `gem5_integration/gem5/src/dev/generic_accel/`; `swig` is missing, no `gem5.opt` exists, no build/dry-run proof has been integrated yet, and no L4 runtime proof has run.
- Full-SCF numerical closure: still non-final; no trusted `qe_accelerated_numeric_evidence.json` plus `full_scf_runtime_trace.json` or `full_scf_row_accounting.json` seed was found. The next safe action is a measured-seed locator/producer decision that remains fail-closed for proxy/smoke/materialized-only rows.
- DFT full-flow final audit and final prompt-to-artifact release audit: blocked until upstream evidence rows are current, trusted, and fail-closed.

Current/next adaptive slot table:

| Slot | Lane family | Objective | Writable scope | Status rule |
| --- | --- | --- | --- | --- |
| slot-1 | run1 | Bind/probe a real `dft_deployment_decision_summary.json` through the release-package path and record whether frozen-universe candidate identity passes or blocks. | `.omx/context` output only unless explicitly isolated | No `dft-*::map_*` -> `cdse_*` crosswalk; no completion upgrade. |
| slot-2 | run2/IC-EDA | Capture or definitively block hash-backed FPGA capacity and ASIC target-library raw-source transcripts using controller/non-read-only IC/EDA access. | `.omx/context` output only | Do not fabricate target JSONs; keep FPGA and ASIC gates separate. |
| slot-3 | run3/verification | Locate or decide the producer path for a trusted full-SCF runtime/numerical seed pair. | read-only or isolated `.omx/context` output | No QE placeholder, h_psi-only, proxy, or smoke evidence upgrade. |
| slot-4 | run2/gem5 | Recheck or unblock `swig`/gem5 build dependency path before any L4 proof attempt. | read-only/probe | No package installs without an explicit recorded provisioning decision; no L4 proof claim from source presence. |
| slot-5 | controller support | Maintain liveness/model-effort/status evidence and manifest gaps for the next wave. | read-only | Count unique final targets, not wrapper process duplicates; no `xhigh` workers. |

As of the current active goal run, the controller should resume from `.omx/context/adaptive-five-slot-barrier-20260527T022930Z-adaptive-five-slot-wave-20260527T022040Z-terminal-handoff.md` and relaunch or backfill up to five slots only when their writable scopes are independent or explicitly barrier-isolated. Preserve dirty state before merge-like actions; do not keep fake keepalive sentinels active merely to make the live count appear as 5/5.

This checkpoint is a current controller state, not completion evidence. It must be superseded by newer barrier artifacts as the run proceeds.

## Done when

1. An adaptive preflight checkpoint exists under `.omx/context` and proves the intended lane topology, per-slot team plan, model routing, launch commands / configs, smoke-debug evidence, and completion-detection evidence.
2. The preflight and each slot handoff prove the Superpowers / skills workflow was followed: `using-superpowers` loaded first, relevant slice skills named, and verification / completion skill gates recorded.
3. The required active slots for each wave have each either completed a verified handoff or recorded a concrete monitor-classified blocker with exact commands, artifacts, and next action. No slot is left silently idle, misassigned, lost before `wrapper.done`, terminal-artifact-incomplete, timed out without classification, or accidentally running with blanket `xhigh`.
4. A north-star system spec exists and is kept current under `.omx/context` or docs, defining the QE workload-to-FPGA/ASIC DSE goal, including deployment-boundary search, runtime / co-scheduling search, FPGA / ASIC / CIM-as-template semantics, evidence gates, and claim boundaries.
5. The repository can ingest or represent QE workload inputs through a workflow-level contract: QE input bundle, pseudopotentials, workflow stages, dependencies, artifacts, correctness tolerances / oracles, baseline commands, hardware-relevant features, DFT/QE reference profile/schema, and descriptor-plus-runnable-bundle workload inputs.
6. The search system generates a finite, reproducible release universe that includes the six representative SCF workload classes, deployment boundaries, architecture templates / modules, mapping / layout policies, runtime / co-scheduling policies, target platforms, legality / pruning decisions, and stable candidate IDs.
7. The system records a complete candidate × workflow-case × deployment-boundary × target × evidence-gate matrix where every row is `trusted_pass`, `trusted_fail`, `pruned_with_reason`, `blocked_missing_input`, `blocked_tool_unavailable`, `blocked_invalid_evidence`, or `projection_only_not_claimable`.
8. The system can produce separate best / Pareto FPGA and best / Pareto ASIC implementation recommendations for an input QE workload or release workload suite, with deployment boundary, architecture / modules, mapping / layout, runtime / co-schedule, expected metrics, comparison rationale, evidence level, blockers, and claim boundaries.
9. FPGA recommendations are gated by FPGA-appropriate evidence paths when claimed: HLS / RTL simulation or synthesis plus Vivado synthesis / implementation / timing / utilization where feasible; otherwise the report marks the FPGA claim blocked or projection-only.
10. ASIC recommendations are gated by ASIC-appropriate evidence paths when claimed: RTL simulation plus Synopsys DC synthesis / timing / area / power where feasible; otherwise the report marks the ASIC claim blocked or projection-only.
11. System-level evidence includes descriptor / runtime ABI accounting, SystemC / generic simulator evidence, gem5 GenericAccel descriptor / completion evidence where feasible, QE-side correctness / baseline comparison, transfer / sync accounting, and CPU-retained stage accounting.
12. Final reports include requirement-evidence matrix, workload coverage report, deployment-boundary search report, candidate generation / provenance report, candidate × workflow evidence ledger, claim validation report, blocker report, artifact hash manifest, and prompt-to-artifact checklist.
13. Adversarial tests or audits prove fail-closed behavior for forged evidence, missing rows, top-k / fixed-candidate downgrades, smoke-only evidence, projection-only evidence, tool-unavailable evidence, and incomplete full-workflow accounting.
14. Fresh verification evidence exists: targeted Python tests, `python3 -m compileall dse_v2`, relevant SystemC / generic simulator build / ctest or documented blocker, relevant pilot / full-flow scripts or documented blocker, gem5 / L4 evidence or documented blocker, and IC / EDA tool attempts when FPGA / ASIC numeric claims are implicated.
15. The final status explicitly distinguishes `vertical_slice_only`, `MVP_partial`, `blocked`, `projection_only`, and `deliverable_complete`. `deliverable_complete` is false unless every claimed FPGA / ASIC recommendation has matching evidence gates.
16. The round lifecycle is actually used: each wave has preflight, parallel dispatch, quiet follow-up, and barrier integration records; the master does not stop after the first successful slot unless the global `Done when` list is satisfied.

## Verification commands

Minimum local verification after document-only changes:

```bash
python3 - <<'PY'
from pathlib import Path
s = Path("docs/goal.md").read_text()
lower = s.lower()
required = [
    "Clarified current intent",
    "Controller mission",
    "Goal hierarchy",
    "Global status:",
    "deliverable_complete semantics",
    "Slot counting rules",
    "Human-readable implementation roadmap",
    "Adaptive replanning algorithm",
    "Worker prompt template",
    "Reassignment protocol",
    "Barrier authority",
    "Objective",
    "Scope",
    "Constraints",
    "Done when",
    "Stop if",
    "Barrier loop",
    "Current active checkpoint",
    "Verification commands",
]
missing = [item for item in required if item not in s]
assert not missing, missing
invariants = [
    "codex exec",
    "live child pid",
    "completion proof requires",
    "active slots: n/5",
    "model_reasoning_effort",
    "blanket `xhigh`",
    "using-superpowers",
    "missing skill workflow instructions are a launch blocker",
    "terminal_artifacts_incomplete",
    "deliverable_complete",
    "repository-wide terminal status owned by the master/controller",
    "fpga recommendations are gated",
    "asic recommendations are gated",
    "more than five concurrent task-bearing units",
    "a slot frees capacity only after",
    "the latest barrier record",
]
missing_invariants = [item for item in invariants if item not in lower]
assert not missing_invariants, missing_invariants
PY
bash -n .omx/context/adaptive_codex_worker_launcher.sh .omx/context/adaptive_codex_worker_monitor.sh
```

If a current adaptive preflight smoke artifact exists, also verify its scheduler and monitor evidence before using it as launch proof:

```bash
python3 - <<'PY'
from pathlib import Path
preflights = sorted(Path(".omx/context").glob("adaptive-five-slot-preflight-*.md"))
if preflights:
    preflight = preflights[-1]
    rows = [line for line in preflight.read_text().splitlines() if line.startswith("| slot-")]
    assert len(rows) <= 5, (preflight, len(rows))
smokes = sorted(Path(".omx/context").glob("adaptive-five-slot-preflight-*-smoke.log"))
if smokes:
    smoke = smokes[-1].read_text()
    for token in ["status=completed", "status=nonzero-return-blocker", "status=lost_before_done", "smoke=passed"]:
        assert token in smoke, token
print("adaptive-goal-doc-context-ok")
PY
```

Minimum implementation-wave verification, when code changed:

```bash
python3 -m pytest -q dse_v2/tests
python3 -m compileall dse_v2
cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
cmake --build model/generic_sim_backend/build -j
ctest --test-dir model/generic_sim_backend/build --output-on-failure
```

## Stop if

- More than five concurrent task-bearing units are active or planned across primary workers, native helper agents, OMX team workers, reviewers, verifiers, and probe agents. Immediately stop dispatch, classify the excess slot(s), and repair the scheduler table before continuing.
- The adaptive preflight is missing, stale, or does not prove the actual launch / model / team / monitor configuration.
- The master or any slot worker starts planning, editing, testing, or completion reporting without first loading `using-superpowers` and the relevant task skills for that slice.
- Any spawned child agent starts coding, debugging, or verification without first loading `using-superpowers` and the task-appropriate skills.
- Any `run1` / `run2` / `run3` worker is launched with accidental inherited blanket `xhigh`, or the live process list contradicts the recorded model plan.
- A slot is assigned work without a recorded lane objective, writable scope, test plan, artifact handoff path, and blocker condition.
- The master stops after one slot turns green without either launching the next round or entering barrier integration to reconcile the remaining slots.
- Any worker proposes or implements a result that hard-codes a fixed top-k candidate set as the final search universe without candidate-generation provenance and pruning rationale.
- Any report or artifact sets `deliverable_complete=true` while any claimed candidate × workflow × target evidence row is missing, blocked, projection-only, smoke-only, or tool-unavailable.
- Any FPGA claim is supported only by ASIC / DC evidence, or any ASIC claim is supported only by FPGA / Vivado evidence.
- Existing tests begin failing after a change; treat this as a regression and do not "fix" it by weakening or deleting tests unless a separate documented test-contract migration is justified.
- Required QE, gem5, Vivado, DC, or other real-tool access is unavailable after concrete attempts; record exact commands, environment, failures, and mark affected claims blocked rather than substituting mocked evidence.
- A merge / rebase / cherry-pick would overwrite dirty or untracked worker changes. Preserve or integrate the worker changes first.
- The plan has not been updated after a major worker result, blocker, evidence run, launch-config change, or integration step; update the living plan before continuing execution.
- When a `Stop if` condition triggers, the controller must record the exact blocker, affected slots, last safe artifact, commands already run, and the next required human or environment action. Stopping is a classified handoff state, not silent abandonment.
