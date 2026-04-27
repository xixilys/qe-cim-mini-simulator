# QE shell clustered FPGA v1 workload bucket mapping (2026-04-02)

## 1. Context

This note is an implementation-facing companion to the clustered v1 freeze and architecture-model documents. It codifies how the current device-oriented matrix (`si4_pbe_uspp_small`, `si8_pbe_uspp`, `graphene_pbe_uspp`, `au_slab_subspace`, `sic32_subspace`) fits into consistent workload buckets, which clusters see the most pressure, and what parameter regimes the v1 baseline should expose when exercising each case. The source of truth for sizes and dominant numerics is `docs/benchmarks/qe_device_oriented_workload_matrix_v0.md` and the clustered v1 spec (`docs/architecture/qe_fpga_clustered_v1_freeze_spec_20260402.md` / `qe_fpga_clustered_v1_architecture_model_v0.md`).

## 2. Bucket rules

### 2.1 Bucket assignment rule

Bucket assignment is frozen as a two-step rule so later scripts can reproduce the same parameter choice without relying on ad hoc manual overrides.

1. Compute a **base size bucket** from `max_subspace_n` first, because reduced-dimension pressure is what most directly determines `Cluster B/C/D` sizing:
   - `small`: `max_subspace_n ≤ 16`
   - `medium`: `16 < max_subspace_n ≤ 32`
   - `large`: `max_subspace_n > 32`
2. Use `npw` and `nkb` only as **pressure modifiers** inside the bucket, not as the bucket selector itself:
   - if `npw > 3\,500`, mark the case as `stream-heavy`
   - if `nkb ≥ 144`, mark the case as `projector-heavy`
   - if both hold, mark the case as `stream-heavy + projector-heavy`

This rule is intentionally not a pure-`npw` classifier. The reason is that `si8_pbe_nc` and `si8_pbe_uspp` have the same reduced-space envelope (`max_subspace_n = 32`) but different full-space pressure. Under the frozen implementation contract they should therefore share the same base bucket (`medium`) while driving different parameter choices inside that bucket.

### 2.2 Size bucket meaning

- `small` workloads: sanity checks and minimal device prototypes. They stress panel scheduling and controller cadence without requiring large reduced-basis storage.
- `medium` workloads: balanced full A/B/C/D cycles with manageable spill risk. They are the main first-board tuning target because they exercise the complete clustered episode path without immediately turning every run into a memory-capacity study.
- `large` workloads: reduced-space or interface-heavy cases that can saturate resident budget, `Cluster C/D`, or both; these define the first hard crossover points for fallback and spill policy.

### 2.3 Projector intensity and pseudopotential style

- `NC-light` workloads: `nkb ≤ 64` and `overlap` couplings are sparse; they lean on `si` bulk solved with norm-conserving (NC) pseudopotentials and therefore put comparatively less pressure on `projector_bank_kib` or `a_stream_lanes`.
- `USPP/PAW-heavy` workloads: `nkb ≥ 72` and/or multiple projector per band (e.g., USPP or PAW); they focus pressure on `projector_bank_kib`, `a_partial_fifo_kib`, and `cluster B` accumulators because more partials must be generated per `psi_panel` sweep.

## 3. Workload compatibility mapping

Each subsection below lists the bucket, axis classification, expected cluster pressure, first bottleneck inferred from the YAML spec, and recommended parameter regime to keep the inter-cluster exchange within the measured envelope.

### 3.1 `si4_pbe_uspp_small`

- **Bucket / axis:** `small` / `USPP-heavy`. Pressure tag: `balanced-stream`. `npw=1\,473`, `nkb=72`, `max_subspace_n=16`.
- **Expected cluster pressure:** Cluster A dominates because the panel size is small but the overlay of USPP projectors gives high per-row partial counts. Cluster B sees moderate reduction pressure because `H_sub/S_sub` remain narrow.
- **Likely first bottleneck:** A→B FIFO saturation due to `a_partial_fifo_kib` (per architecture spec section 5) when `row_block_size` is tuned for 3–4 bands per panel; `fifo_ab` needs to stay above 90% occupancy before the controller slows new `psi_panel` issuance.
- **Recommended regime:** Keep `panel_bands` moderate (4–6) and `row_block_size` low so `a_array_lanes` can finish each partial quickly, provision `a_partial_fifo_kib` around the same Kib as the `psi_panel_kib`, and keep `fifo_ab_kib` tall (≥ `projector_bank_kib`) to hold short bursts. Because `ResidentFootprint` easily fits, minimize `spill_penalty` edits.

### 3.2 `si8_pbe_uspp`

- **Bucket / axis:** `medium` / `USPP-heavy`. Pressure tag: `projector-heavy`. `npw=2\,945`, `nkb=144`, `max_subspace_n=32`.
- **Expected cluster pressure:** Balanced A/B/C pressure; `a_stream_lanes` must stream larger panels, `b_accum_lanes` aggregate more partials, and `c_input_buffer_kib` begins to hit fast fill limits as `n_active` nears `c_reduced_dim_cap`.
- **Likely first bottleneck:** B→C emission because `b_reduced_emit_bw_kib_per_us` must move expanded reduced matrices while `c_input_buffer_kib` has finite staging; `stall_ratio_bc` in the spec’s metrics will spike before C begins compute.
- **Recommended regime:** Increase `b_reduced_stage_kib` to absorb combination of `H_sub`/`S_sub`, keep `b_accum_lanes` > 4, and set `c_input_buffer_kib` equal to the worst-case `byte_count` for the `panel_serial`. `c_reduced_dim_cap` should comfortably exceed the measured `max_subspace_n` (32) so C never falls back to companion solver.

### 3.3 `graphene_pbe_uspp`

- **Bucket / axis:** `small` / `NC-light-like` (although the software setup is USPP, `nkb=16` keeps the hardware pressure on the NC-light side). Pressure tag: `controller-heavy`. `npw=1\,105`, `max_subspace_n=8`, `max_subspace_m=4`.
- **Expected cluster pressure:** Lightweight A and B but frequent C/D rendezvous because `n_active` stays small while episodes loop quickly; D’s refresh lanes see the most relative utilization as each diagonalization is short but repeated frequently.
- **Likely first bottleneck:** Controller-mediated stalls due to `controller_sync_us` when `panel_serial` cadence is high; the credit return delay multiplies `stall_ratio_cluster` across all links.
- **Recommended regime:** Keep `a_stream_lanes`/`b_accum_lanes` low (2–3), reduce `a_partial_fifo_kib` so `fifo_ab` drains quickly, and prioritize `controller_sync_us` tuning (fast credit return) so the per-panel `stall_ratio` stays under 30%. Because `resident_fit` is trivially satisfied, minimize off-chip fetches by setting `resident_hint`=true for all descriptors.

### 3.4 `au_slab_subspace`

- **Bucket / axis:** `large` / `USPP-heavy`. Pressure tag: `stream-heavy + projector-heavy`. Interface geometries drive large `npw`/`nkb`, and `max_subspace_n` exceeds 32; this is a contact/interface stress test.
- **Expected cluster pressure:** Cluster C/C→D dominate: large reduced matrices fill `c_input_buffer_kib` and `c_emit_bw_kib_per_us`, while D’s writeback lanes and `d_pnext_slots_kib` must drain entire slabs.
- **Likely first bottleneck:** C→D emission. `diag_solution_descriptor` emission outruns D’s `refresh_lanes` (spec section 5) unless `c_emit_bw_kib_per_us` is dialed down or `d_writeback_bw_kib_per_us` raised.
- **Recommended regime:** Maximize `c_solver_parallelism` to keep `T_C_compute` manageable, keep `c_emit_bw_kib_per_us` matched to D’s `d_writeback_bw_kib_per_us`, enlarge `d_refresh_buffer_kib`, and monitor `Bytes_spill` because spills are expensive when the slab pushes `ResidentFootprint` beyond budget. Consider gating `panel_serial` issuance so `fifo_cd` never stays over 90% for longer than `controller_sync_us`.

### 3.5 `sic32_subspace`

- **Bucket / axis:** `large` / `NC-light`. Pressure tag: `stream-heavy`. Wide-bandgap geometry has large `npw` but fewer pseudopotential projector types, so `nkb` remains moderate while `max_subspace_n` is high.
- **Expected cluster pressure:** Cluster B contributions grow because `H_sub/S_sub` require wide reductions, but Cluster C/D remain the gating path due to big `diag_solution` context and tight refresh windows for `SiC` (per spec section 5).
- **Likely first bottleneck:** C→D handoff backed up by D’s refresh window; if `bytes_cd_peak` spikes, `cdiaghg_mode_selected` should fallback to companion to avoid `Bytes_spill` surges.
- **Recommended regime:** Keep `b_accum_buffer_kib` and `b_reduced_stage_kib` large enough to stage `n_active ≈ max_subspace_n`, set `c_reduced_dim_cap` so it can handle `sic32`’s `n_active` but also have a controlled fallback threshold, and provision `d_refresh_lanes`/`d_writeback_bw_kib_per_us` to align with the expected `solution_span`. Allow `spill_flag` to pre-mark B→C descriptors when `ResidentFootprint` threatens `onchip_resident_budget_kib`.

## 4. Proposed medium-weight addition: `si8_pbe_nc`

- **Why add:** The current matrix already pairs `si8_pbe_uspp` with its NC sibling in section 3 of the workload matrix doc. Adding `si8_pbe_nc` keeps the bulk-Si transport baseline consistent with both pseudopotential styles and lets us observe how a NC-light variant shifts pressure toward Cluster A and the controller (less `projector_bank_kib` usage, smaller `a_partial_fifo_kib`).
- **Bucket / axis:** `medium` / `NC-light`. Pressure tag: `stream-heavy`. `npw=4\,553`, `nkb=64`, `max_subspace_n=32`.
- **Expected cluster pressure:** Cluster A sees longer panels because `npw` rises, but B/C keep more headroom due to lighter projector intensity. The controller must keep `fifo_ab` deep to accommodate large `psi_panel_kib`, so `residence_hint` accuracy is critical.
- **Likely first bottleneck:** A→B and credit return interplay. `fifo_ab_peak_depth` may stay high while `controller_sync_us` tries to keep credit pipelines full; this is the first sign before B even attempts to push reduced matrices to C.
- **Recommended regime:** Spread `row_block_size` into larger chunks to avoid per-panel overhead, keep `a_array_lanes`/`a_stream_lanes` scaled to the new `npw`, and still provision `b_reduced_stage_kib` for the identical reduced-dimension load that `si8_pbe_uspp` generates. `resident_hint` should default to true because the NC path can keep more data on-chip.

## 5. Executable summary table

| case | base bucket | mode axis | pressure tag | why it lands here |
| --- | --- | --- | --- | --- |
| `si4_pbe_uspp_small` | `small` | `USPP-heavy` | `balanced-stream` | `max_subspace_n = 16` fixes the case in `small`; `nkb = 72` makes it projector-heavy enough to stay on the USPP side. |
| `si8_pbe_uspp` | `medium` | `USPP-heavy` | `projector-heavy` | `max_subspace_n = 32` fixes the base bucket at `medium`; `nkb = 144` makes it the projector-heavy medium baseline. |
| `graphene_pbe_uspp` | `small` | `NC-light-like` | `controller-heavy` | `max_subspace_n = 8` keeps the reduced-space load small; low `nkb` means the main stress is controller cadence rather than projector accumulation. |
| `au_slab_subspace` | `large` | `USPP-heavy` | `stream-heavy + projector-heavy` | This is both a large reduced-space and a high-traffic interface case, so it is the large USPP reference. |
| `sic32_subspace` | `large` | `NC-light` | `stream-heavy` | The reduced-space envelope places it in `large`, while moderate projector intensity keeps it on the NC-light side. |
| `si8_pbe_nc` | `medium` | `NC-light` | `stream-heavy` | `max_subspace_n = 32` keeps it in the same base bucket as `si8_pbe_uspp`; the larger `npw` changes the pressure tag, not the bucket. |

## 6. Reporting guidance

When validating these mappings, log the same metrics called out in the inter-cluster exchange spec (`fifo_*_peak_depth`, `stall_ratio_*`, `Bytes_spill`, `resident_fit`, etc.) and tag them with the workload label. That makes it easy to correlate predicted bottlenecks above with actual `panel_serial` windows and to see whether `cdiaghg_mode_selected` changes for the large workloads.
