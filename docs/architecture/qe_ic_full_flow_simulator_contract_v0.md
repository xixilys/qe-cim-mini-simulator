# QE IC-oriented full-flow simulator contract (v0, 2026-04-16)

## 0. Purpose and scope

This document freezes the **Step 1 foundation contract** for the IC-oriented `QE` full-flow simulator lane approved in `.omx/plans/ralplan-final-ic-oriented-full-flow-simulator-dse-20260416.md`.

The contract exists to turn the current brownfield runnable model into an **execution-ready system object** for:

- `QE-connected SCF / band-solver shell` simulation;
- host/device co-debug on the full shell path;
- architecture-family DSE with explicit fairness, observability, and correctness gates; and
- later board / GPU / QE-gold closure without redefining the simulator semantics again.

The scoped system object is still:

- `rho -> Veff`
- `while bands not converged { h_psi, s_psi, build H_sub / S_sub, cdiaghg, refresh / residual -> P_next }`
- `psi -> rho_out`
- `mix_rho / convergence gate`

This contract is **not** a new solver line and **not** a replay-first runtime. It is a contract for one promoted simulator scaffold that keeps the current public host-device objects and upgrades their semantics.

### 0.1 Contracted inputs

Every claim-bearing simulator run must be anchored by three input classes:

| Input class | Required role | Notes |
| --- | --- | --- |
| `case descriptor` | selects workload identity, shell shape, tolerance, workload-group membership, strategy knobs, and join keys | This is the authoritative runtime input. |
| `trace / gold / calibration inputs` | ground shape, calibrate selected numerical surfaces, and validate outputs | They constrain the simulator; they do not replace it. |
| `GPU comparison metadata` | pins fairness policy, accounting boundary, power boundary, and decisive-baseline context | Required for later `CPU+GPU` vs `CPU+FPGA` closure. |

### 0.2 Contracted execution surfaces

The simulator state machine is frozen at the following semantic surfaces:

1. **case load / descriptor bind**
2. **outer SCF control**
3. **inner hot-path episode execution**
4. **diag / fallback / host-assist path**
5. **convergence and error-surface update**
6. **validation / reporting / claim gate**

The simulator may still reuse the current brownfield module path (`HostSCF -> FPGAOrchestrator -> ChipTop`), but all future edits must preserve these surfaces as the public semantic boundary.

## 1. One scaffold / two lanes model

The approved architecture is **one scaffold / two lanes**, not two separate simulators.

### 1.1 Shared scaffold

Both lanes share the same top-level scaffold:

- `HostSCF` as host functional runtime and outer-shell owner;
- `FPGAOrchestrator` as thin device runtime / bridge;
- `ChipTop` and the cluster-first datapath as the inner device execution anchor;
- the existing `F1/F2/F3` family scaffold;
- the same workload identity, fairness ids, observability ids, tolerance ids, and report join keys.

### 1.2 Lane split

| Lane | Main role | Allowed semantic style | Primary output role |
| --- | --- | --- | --- |
| **Lane 1 — fast / timed-functional lane** | broad screening, family ranking, strategy search, artifact continuity | may retain screened proxy summaries and timing/traffic approximations | DSE ranking, candidate pruning, explain-only evidence |
| **Lane 2 — numerically grounded lane** | selected-case validation, descriptor/calibration-driven state update, claim-bearing assessment | must prefer descriptor-driven, calibrated, or gold-checked numerical surfaces | correctness-capable validation and thesis-facing evidence |

### 1.3 Hard rule

The lane split is a **semantic discipline**, not a directory split:

- Lane 1 keeps the current fast-layer role from `docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json`.
- Lane 2 aligns with the current accurate-layer role and the `si8_pbe_nc` anchor strategy.
- No field may silently switch from Lane 1 screening semantics into Lane 2 claim semantics without an explicit provenance-tag upgrade.

## 2. Semantic cut line and provenance tags

The simulator must freeze a semantic cut line between:

- **retained fast-lane proxy surfaces**;
- **descriptor-derived or calibrated numerical surfaces**; and
- **measured external evidence** used for validation and closure.

### 2.1 Provenance vocabulary

Every reported quantity that survives beyond local debug output must carry exactly one provenance tag:

| Tag | Meaning | Allowed use |
| --- | --- | --- |
| `proxy` | heuristic or timed-functional stand-in; shape-preserving but not claim-bearing by itself | fast-lane screening only |
| `derived` | deterministically computed from declared descriptor / simulator state without external calibration | allowed in screening and in some claim paths when the contract explicitly permits it |
| `calibrated` | simulator-computed quantity adjusted or constrained by trace/gold/calibration inputs | allowed in selected claim-bearing paths |
| `measured` | externally observed board / QE baseline / sensor / artifact value | authoritative for validation, fairness, and final closure |

### 2.2 Claim rule

A field without a provenance tag is **not admissible** in any claim-bearing summary.

A field tagged `proxy` is **not sufficient** for correctness, fairness, or thesis claims. It may support screening, ranking, or explain-only tables.

### 2.3 Semantic cut-line rule

For every currently proxy-owned quantity, the implementation must classify it as one of:

1. **retained fast-lane proxy**;
2. **replaced by descriptor/derived or calibrated numerical state**; or
3. **removed from the claim-bearing path**.

### 2.4 Initial cut-line guidance

The first execution revision of this contract should follow the approved plan's direction:

- shell summary and architecture-ranking metrics may remain in Lane 1 when clearly tagged `proxy` or `derived`;
- convergence, energy, residual-threshold, and selected iteration-state surfaces must move toward `derived` or `calibrated` semantics in Lane 2;
- observability, fairness, GPU-baseline, and board-closure rows ultimately terminate in `measured` evidence.

## 3. CPU / device responsibilities

The simulator remains **host-managed**. Responsibilities are frozen as follows.

### 3.1 CPU-side responsibilities

The CPU side owns:

- outer `SCF` control and state progression;
- descriptor binding and runtime policy interpretation;
- `rho -> Veff`, `mix_rho`, convergence gating, and error-surface ownership;
- diag placement decisions, host-assist, and fallback policy;
- construction of claim-visible iteration/run summaries;
- ingestion of trace/gold/calibration inputs;
- final correctness, fairness, and reporting handoff.

### 3.2 Device-side responsibilities

The device side owns:

- inner hot-path execution under the offload contract;
- resident preload / reuse, DMA, spill, and device execution bookkeeping;
- hardware-path realization of the selected inner-loop operators through the existing cluster-first datapath;
- completion summaries needed by the host runtime;
- counters and event surfaces required by the observability contract.

### 3.3 Responsibility table

| Surface | CPU / host functional runtime | Device runtime / datapath |
| --- | --- | --- |
| outer SCF loop | authoritative owner | not owner |
| descriptor interpretation | authoritative owner | consumes bound request |
| offload / diag / fallback policy | authoritative owner | executes selected policy |
| resident / DMA scheduling | policy owner / verifier | execution owner |
| shell convergence state | authoritative owner | reports inputs to owner |
| end-of-iteration numerical state | authoritative owner in public contract | contributes episode outputs only |
| counters for observability | validates / joins / reports | emits runtime and datapath counters |
| final correctness / fairness claim | authoritative owner | evidence source, not claim owner |

### 3.4 Hard boundary

The CPU runtime must stop behaving as an unconstrained heuristic generator for convergence and energy state. The device path must stop being interpreted as the owner of outer-shell correctness. The contract is explicitly **CPU-owned shell semantics + device-owned inner execution evidence**.

## 4. Trace / gold role: grounding, calibration, validation — not replay

Trace and QE-gold artifacts are frozen as **grounding inputs**, not the primary runtime.

### 4.1 Allowed roles

| Artifact class | Allowed role |
| --- | --- |
| trace-derived shape / shell aggregates | ground workload shape, operator mix, iteration structure, and selected timing/traffic calibration |
| canonical QE gold baseline | validate final energy / convergence / tolerance compliance |
| board / GPU measured artifacts | validate simulator projections, fairness closure, and observability alignment |

### 4.2 Disallowed role

The simulator must **not** be redefined as:

- strict replay of trace rows;
- a log-player that bypasses simulator state updates; or
- a claim system where external artifacts substitute for simulator-computed semantics.

The legacy replay/body path can remain as compatibility tooling, but it is not the governing semantic contract for this line of work.

### 4.3 Operational rule

A good trace/gold artifact can:

- constrain descriptor values;
- calibrate selected timing / traffic / fallback surfaces;
- validate convergence and final-state outputs;
- downgrade confidence when the simulator drifts.

It cannot:

- define the only runtime state transition path; or
- convert a `proxy` field into a claim-bearing field without an explicit `calibrated` or `measured` transition.

## 5. Fidelity ladder

The simulator fidelity ladder is frozen as a staged progression inside the same scaffold.

| Fidelity level | Meaning | Expected use |
| --- | --- | --- |
| **L0 — shell-contract bring-up** | full shell path present, but many numerical surfaces still remain proxy or coarse derived state | early bring-up, control/debug, fast continuity |
| **L1 — reduced-space grounded simulator** | descriptor-driven shell control plus calibrated reduced-space or selected numerical surfaces for chosen cases | accurate-layer anchors, selected-case validation |
| **L2 — numerical-close-to-QE simulator** | selected claim surfaces are numerically close enough to QE gold to support correctness-capable assessment under the frozen tolerance contract | claim-bearing promotion and thesis-facing comparisons |

### 5.1 Ladder discipline

- `L0` is acceptable for broad DSE screening but not for thesis claims.
- `L1` is the expected entry point for `si8_pbe_nc` and other accurate-layer anchors.
- `L2` is required before the simulator can support same-correctness/tolerance claims beyond explain-only status.

Advancement on the ladder is case- and surface-specific. A run does not become fully `L2` merely because one metric was calibrated.

## 6. Claim boundary and non-goals

### 6.1 What this contract allows the simulator to claim

If joined to the existing correctness, fairness, and observability contracts, this simulator contract can support:

- family-level DSE ranking and candidate pruning;
- descriptor- and calibration-grounded selected-case validation;
- explainable attribution of resident / DMA / fallback / host-assist effects;
- correctness-capable comparison against frozen QE gold baselines; and
- later `CPU+FPGA` vs `CPU+GPU` closure, once the fairness lane is populated with admissible measured artifacts.

### 6.2 What this contract does not allow by itself

This document alone does **not** authorize claims that:

- the simulator is a numerically faithful full `QE` implementation;
- phase-1 `CPU+FPGA > CPU+GPU` thesis is already proven;
- proxy-only timing or energy numbers are already publishable as measured results;
- replay compatibility equals numerical validity; or
- `F3` is promotion-ready without the same observability and correctness closure expected of `F1/F2`.

### 6.3 Explicit non-goals for this phase

This phase does **not** make the following the mainline objective:

- RTL implementation or RTL-accurate closure;
- gem5 / full-system host realism;
- OS / driver / cache-hierarchy debugging as the main bottleneck;
- replacing the family-based scaffold with a new taxonomy; or
- using toy/debug workloads to redefine the device-oriented workload matrix.

## 7. Links to existing repo contracts and taxonomy

This contract is intentionally additive. It depends on, and must remain aligned with, the following existing repo surfaces.

### 7.1 Primary grounding documents

- `docs/architecture/host_managed_full_scf_architecture_v1_20260409.md` — current host-managed scaffold and next-step uplift direction
- `model/qe_band_solver_model/README.md` — promoted runnable-model contract and public host/device objects
- `docs/overview/agent_handoff_20260312.md` — current modeling/system-exploration phase priority

### 7.2 DSE lane and workload taxonomy

- `docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json` — fast-layer / accurate-layer scaffold, anchor cases, and promotion policy
- `docs/benchmarks/qe_device_oriented_workload_matrix_v0.md` — device-oriented workload roster and role taxonomy
- `docs/benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md` — case-state, decisive-lane, and admission discipline
- `docs/architecture/systemc_system_level_dse_family_responsibility_matrix_v0_20260413.md` — `F1/F2/F3` responsibility split for advisor-facing DSE interpretation

### 7.3 Correctness, fairness, and observability contracts

- `docs/benchmarks/qe_gold_correctness_contract_v0.md` — canonical QE gold fields and tolerance gate
- `docs/benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md` — shared-rewrite, decisive GPU baseline, and whole-node power boundary
- `docs/benchmarks/qe_simulator_board_observability_contract_v0.md` — join keys and simulator↔board comparison surfaces
- `docs/benchmarks/qe_cpu_gpu_baseline_acquisition_runbook_v0.md` — GPU-baseline state vocabulary and acquisition discipline

### 7.4 Reporting / advisor pack continuity

- `docs/architecture/systemc_system_level_dse_confidence_and_claims_rubric_v0_20260413.md`
- `docs/architecture/systemc_system_level_dse_advisor_report_template_v0_20260413.md`
- `docs/architecture/systemc_system_level_dse_advisor_docs_index_v0_20260413.md`

These documents remain the reporting layer. This contract defines the simulator semantics that those reporting artifacts are allowed to summarize.

## 8. Frozen execution rules for Step 1 follow-on work

Until this contract is revised, the follow-on implementation work must obey the following rules:

1. **Do not replace the scaffold.** Upgrade semantics inside the existing host-managed scaffold.
2. **Do not collapse the two lanes.** Fast screening and numerically grounded validation remain distinct roles.
3. **Do not hide provenance.** Every surviving field must carry `proxy`, `derived`, `calibrated`, or `measured` provenance.
4. **Do not turn trace into runtime truth.** Trace/gold grounds and validates; simulator computes.
5. **Do not overclaim.** Thesis-bearing statements require the downstream correctness, fairness, and observability contracts to pass with admissible evidence.

This is the foundation contract for Step 1. Later schema, runtime, and DSE changes should refine this contract, not silently bypass it.
