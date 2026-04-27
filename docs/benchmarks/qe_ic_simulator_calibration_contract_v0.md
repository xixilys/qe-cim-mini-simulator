# QE IC simulator calibration contract v0

## 1. Purpose

This document freezes the Step-2 foundation contract for the IC-oriented full-flow QE simulator work.

It defines four things before runtime changes land:

1. the authority hierarchy between the existing phase config and the new IC overlay;
2. the descriptor/calibration fields that must exist before a case enters either simulator lane;
3. the join-key/export mapping required for simulator, GPU baseline, and board evidence closure;
4. the ownership split between the fast/timed-functional lane and the numerically grounded lane.

This revision also makes the overlay explicitly consume:

- `docs/benchmarks/qe_ic_computational_signature_taxonomy_v0.md`
- `docs/benchmarks/qe_ic_case_signature_matrix_v0.json`

## 2. Authority hierarchy (normative)

### 2.1 Baseline authority stays where it is

`docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json` remains the **baseline authority** for the current family-based, two-layer DSE scaffold.

It continues to own:

- the baseline `F1` / `F2` / `F3` family framing;
- the `fast_layer` vs `accurate_layer` split;
- the current release-facing ranking and promotion semantics.

### 2.2 New IC config is a derived overlay, not a replacement

`docs/benchmarks/qe_ic_full_flow_phase_config_v0.json` is introduced as a **derived overlay**.

Until a compatibility adapter/exporter is stable, the overlay is allowed to:

- add descriptor, calibration, and GPU-baseline metadata;
- tighten lane ownership and claim boundaries;
- define export aliases needed by observability and fairness tooling.

Until that adapter/exporter is stable, the overlay is **not** allowed to silently replace the baseline config as the single source of truth.

### 2.3 Promotion gate for future authority transfer

The overlay may only be promoted beyond derived-overlay status after all of the following are true:

1. export to the current `qe_next_stage_dse_simulator_phase_config_v0.json` semantics is lossless for the family/two-layer scaffold;
2. the adapter/exporter preserves the current phase-driver expectations for `fast_layer`, `accurate_layer`, and family sweep semantics;
3. observability/fairness validators consume the exported join keys without alias drift.

## 3. Machine-readable surfaces in scope

This contract directly governs:

- `docs/benchmarks/qe_next_stage_dse_simulator_phase_config_v0.json` (baseline authority)
- `docs/benchmarks/qe_ic_full_flow_phase_config_v0.json` (derived overlay)
- `docs/benchmarks/qe_ic_computational_signature_taxonomy_v0.md` (signature taxonomy authority)
- `docs/benchmarks/qe_ic_case_signature_matrix_v0.json` (case × signature map)
- the future compatibility adapter/exporter between them
- the case-pack/descriptors that will feed simulator rows, GPU baseline rows, and board comparison rows

## 4. Descriptor layers and ownership

### 4.1 Shared descriptor core

Every case descriptor must carry a shared core before it is eligible for either lane:

| Field | Required | Lane owner | Join/export role | Notes |
| --- | --- | --- | --- | --- |
| `workload_id` | yes | shared | exact join key | Case identity used by simulator / GPU / board artifacts. |
| `workload_group_id` | yes | shared | exact join key | Must remain stable across simulator, GPU baseline, and board bundles. |
| `family` | yes | shared | exported as `architecture_family` | Keep baseline `family` semantics; exporter emits `architecture_family` for observability joins. |
| `diag_policy` | yes | shared | exact join key | Strategy axis already used by the family DSE sweep. |
| `offload_scope` | yes | shared | exact join key | Strategy axis already used by the family DSE sweep. |
| `resident_policy` | yes | shared | exact join key | Strategy axis already used by the family DSE sweep. |
| `partition_strategy` | yes | shared | exact join / identity key | Signature-aware partition hypothesis axis; must enter machine-readable DSE identity once enabled. |
| `qe_tolerance_schema_id` | yes | shared | exact join key | Must match the QE gold/tolerance contract used by downstream compare tooling. |
| `accounting_boundary_id` | yes | shared | exact join key | Prevents cross-boundary time/energy mixing. |
| `fairness_policy_id` | yes | shared | exact join key | Keeps simulator/GPU/board rows inside the same fairness contract. |
| `power_boundary_id` | yes | shared | exact join key | Must match the whole-node power boundary used for comparison claims. |
| `observability_contract_id` | yes | shared | exact join key | Must close against `qe_simulator_board_observability_contract_v0.md`. |
| `algorithm_rewrite_manifest_id` | yes | shared | exact join key | Links simulator rows to rewrite/fallback assumptions. |
| `algorithm_contract_deviation` | yes | shared | exact join key | Explicitly records any permitted deviation from the frozen algorithm contract. |
| `source_kind` | yes | shared | taxonomy field | Must reuse the existing simulator/source taxonomy verbatim. |

### 4.1a Signature extension core

在 shared core 之外，IC-oriented specialization 还要求每个 case descriptor 携带统一的 signature extension fields：

| Field | Required | Notes |
| --- | --- | --- |
| `signature_id` | yes | 当前 signature 组合的稳定 machine-readable id。 |
| `property_target` | yes | 例如 `band_gap` / `effective_mass` / `transport_proxy`。 |
| `pseudopotential_family` | yes | `NC` / `USPP` / `PAW` / `hybrid`。 |
| `solver_path_class` | yes | `standard_band` / `generalized_overlap` / `hybrid_sensitive` / `post_scf_extension_sensitive`。 |
| `workload_topology` | yes | `bulk` / `2D` / `slab_interface` / `wide_bandgap` / `defect_doped`。 |
| `post_scf_extension_level` | yes | `shell_only` / `nscf_extension` / `dfpt_expected` / `epw_expected` / `mobility_extension_expected`。 |
| `projector_pressure` | yes | signature pressure bucket。 |
| `nonlocal_pressure` | yes | signature pressure bucket。 |
| `generalized_ratio_bucket` | yes | signature pressure bucket。 |
| `diag_dominance` | yes | signature pressure bucket。 |
| `fft_grid_pressure` | yes | signature pressure bucket。 |

Hard rule:
- 这些字段可以扩展 descriptor，
- 但**不能**替换 shared join-key fields，
- 也**不能**破坏当前 fairness / observability / correctness join-key contract。

### 4.2 Fast / timed-functional lane ownership

The fast lane owns broad DSE screening and family ranking continuity.

It is responsible for fields that explain *why a proxy-shaped point was screened the way it was*, not for final claim-bearing numerical closure.

| Field | Required | Meaning |
| --- | --- | --- |
| `trace_shape_id` | yes | Stable identifier for the trace-derived shape bundle used to size the run. |
| `trace_shape_summary` | yes | Compact shape metadata (for example `npw`, `nkb`, `nbnd`, dominant solver share, or an equivalent frozen summary). |
| `canonical_profile_match` | optional | Existing fast-lane screening hint reused from the current DSE sweep. |
| `fast_proxy_assumption_set_id` | yes | Frozen proxy assumption set used for the timed-functional interpretation. |
| `gpu_baseline_state` | yes | Current GPU baseline availability/readiness state for the case. |
| `gpu_baseline_row_ref` | optional | Pointer to the imported GPU row when one already exists. |
| `signature_id` | yes | Fast lane 也必须知道自己在解释哪类 IC-oriented signature。 |

Fast-lane outputs may drive ranking, shortlist formation, and explanation, but they remain non-claim-bearing until the accurate/numerically grounded lane closes the required checks.

### 4.3 Numerically grounded lane ownership

The numerically grounded lane owns descriptor/calibration-driven runtime grounding and claim-bearing validation.

| Field | Required | Meaning |
| --- | --- | --- |
| `calibration_manifest_id` | yes | Stable handle for the trace/gold/calibration bundle used by the numerical lane. |
| `gold_case_bundle_id` | yes | Frozen QE gold baseline bundle used for correctness comparison. |
| `gold_source_path` | yes | Source location of the gold/correctness artifact set. |
| `reduced_space_contract_id` | yes | Identifies the reduced-space / diagonalization validation surface used for the case. |
| `convergence_reference_id` | yes | Convergence reference used for final-state and intermediate-state comparison. |
| `numerical_provenance_tag` | yes | One of `proxy`, `derived`, `calibrated`, or `measured`; required for claim-bearing summaries. |
| `gpu_baseline_state` | yes | Same taxonomy as the fast lane; reused, not redefined. |
| `decisive_for_case` | optional | Independent boolean emitted by readiness/closure tooling; never a substitute for source-kind or baseline-state. |
| `signature_id` | yes | Accurate / numerical lane 的 claim-bearing candidate 必须携带 `signature_id`。 |

## 5. Join-key and export mapping (normative)

The overlay must export descriptor fields into the same join-key tuple expected by the observability/fairness toolchain.

| Overlay field | Exported / downstream field | Required on rows | Notes |
| --- | --- | --- | --- |
| `workload_id` | `workload_id` | simulator, GPU, board | Exact match required. |
| `workload_group_id` | `workload_group_id` | simulator, GPU, board | Exact match required. |
| `family` | `architecture_family` | simulator, GPU, board | Keep baseline family naming in the overlay; exporter emits observability-facing alias. |
| `diag_policy` | `diag_policy` | simulator, GPU, board | Exact match required. |
| `offload_scope` | `offload_scope` | simulator, GPU, board | Exact match required. |
| `resident_policy` | `resident_policy` | simulator, GPU, board | Exact match required. |
| `partition_strategy` | `partition_strategy` | simulator, GPU, board | Exact match required once the overlay enables partition-aware DSE identity. |
| `qe_tolerance_schema_id` | `qe_tolerance_schema_id` | simulator, GPU, board | Exact match required. |
| `accounting_boundary_id` | `accounting_boundary_id` | simulator, GPU, board | Exact match required. |
| `fairness_policy_id` | `fairness_policy_id` | simulator, GPU, board | Exact match required. |
| `power_boundary_id` | `power_boundary_id` | simulator, GPU, board | Exact match required. |
| `observability_contract_id` | `observability_contract_id` | simulator, GPU, board | Exact match required. |
| `algorithm_rewrite_manifest_id` | `algorithm_rewrite_manifest_id` | simulator, GPU, board | Exact match required. |
| `algorithm_contract_deviation` | `algorithm_contract_deviation` | simulator, GPU, board | Exact match required. |
| `request_id` | `request_id` | generated run rows | Run-local join key; not frozen in the phase-config baseline. |
| `scf_iteration` | `scf_iteration` | generated run rows | Run-local join key; appears only after execution. |
| `episode_id` | `episode_id` | generated run rows when applicable | Run-local join key; appears only after execution. |

Hard rule: if the exporter cannot emit this tuple without alias drift, the overlay remains descriptive only and the baseline config continues to govern execution.

## 6. Taxonomy reuse (must not fork)

### 6.1 `source_kind`

The simulator/source taxonomy stays exactly:

- `stub`
- `timed_functional_proxy`
- `trace_calibrated_proxy`
- `measured`
- `mixed`

This contract does **not** introduce a parallel lane taxonomy for the same concept.

### 6.2 GPU readiness / availability states

GPU rows and GPU availability metadata must reuse the current baseline-state vocabulary:

- `pending`
- `running`
- `measured_not_yet_validated`
- `reference_only`
- `deferred`
- `thesis_eligible`

The readiness progression still flows through the existing artifact chain. Imported local GPU artifacts do not get a new shortcut state.

### 6.3 `decisive_for_case`

`decisive_for_case` remains a separate boolean flag emitted by readiness/closure tooling.

It is **not**:

- a replacement for `baseline_state` / GPU readiness state;
- a replacement for `source_kind`;
- a shortcut around correctness, fairness, power, or observability closure.

### 6.4 Stage-B nonblocking rule

`au_slab_subspace` 与 `sic32_subspace` 这类 Stage-B signature cases 在当前版本中：

- 必须进入 signature taxonomy 与 case-signature map；
- 可以进入 descriptor 与 signature-aware DSE interpretation；
- 但在单独 gate change 生效前，仍保持 **nonblocking signature coverage** 身份；
- 不得自动进入当前 release readiness blocking set。

### 6.5 Stage-B inventory note

当前版本允许 Stage-B signature cases：

- 先进入 case-signature map；
- 进入 overlay/config/calibration contract；
- 进入默认 runnable workload inventory；

但它们进入 inventory **不等于** 进入当前 release-blocking set。它们仍然默认是：

- `qe_signature_stage_b`
- nonblocking signature coverage
- only promoted by explicit future gate change

## 7. Lane split summary

| Surface | Fast / timed-functional lane | Numerically grounded lane |
| --- | --- | --- |
| Primary job | broad family/strategy screening | selected-case numerical grounding and claim-bearing validation |
| Typical `source_kind` | `timed_functional_proxy`, `trace_calibrated_proxy` | `trace_calibrated_proxy`, `mixed` (and `measured` only when the row truly comes from measured evidence) |
| Required artifacts | trace-shape descriptor, proxy assumption set, shared join keys | calibration manifest, gold bundle, reduced-space contract, shared join keys |
| Claim status | ranking/explanation only | may support correctness/fairness claims after gates close |
| GPU metadata role | availability/readiness context for screening | readiness/decisive context for closure and comparison packaging |

## 8. Compatibility rule for the future adapter/exporter

The future adapter/exporter must preserve all of the following simultaneously:

1. baseline family semantics (`F1`, `F2`, `F3`);
2. baseline two-layer semantics (`fast_layer`, `accurate_layer`);
3. the shared join-key tuple used by observability and fairness tooling;
4. the unforked taxonomies for `source_kind`, GPU readiness states, and `decisive_for_case`.

Until then, the baseline config remains authoritative and the new IC config remains a derived overlay.
