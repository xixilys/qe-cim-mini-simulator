# Cluster A/B Operator Build Spec (v1 clustered FPGA)

## 1. Purpose

This module-level spec translates the v1 clustered architecture freeze into concrete implementation building blocks for
Cluster A (fused `h_psi + s_psi`) and Cluster B (`build H_sub / S_sub`). It captures the internal module tree, interface
contract, buffer/resident requirements, workload-configurable knobs, sticking points, and cluster-specific KPIs needed to
move from architecture modeling toward RTL/behavioral implementation.

## 2. Cluster A: fused operator sweep implementation

### 2.1 Module tree
- `PsiPanelReceiver`: double-buffered loader that streams `Psi_panel` tiles from off-chip into `Psi_panel_ping` / `Psi_panel_pong`
  bank and tags them with `panel_id` + `row_block` metadata.
- `ProjectorOverlapBank`: episode-resident banks for projector and overlap state that keep `projector_state_bank` and
  `overlap_state` ready for the current panel, updating only when the controller fractures to a new basis block.
- `FFTSupportUnit` (optional): handles support-grid FFT work when `s_psi` needs `Veff` contributions, consuming shared
  `a_fft_lanes` resources and exposing `FFT_ready` tokens for downstream processing.
- `FusedArrayEngine`: `a_array_lanes` lane SIMD / array unit that multiplies `Psi_panel` with projector/overlap data to
  produce `partial_HS` results per `row_block_size` and `panel_bands` sweep.
- `PartialReducer`: local reduction tree that accumulates partial contributions into `partial_HS_packets` sized for the A→B FIFO.
- `PartialEmitter`: interface that pushes packets into `partial_HS_fifo` while monitoring `A_to_B_partial_fifo` depth and `A emit bandwidth`.

### 2.2 Interfaces & buffers
- Inputs: `Psi_panel` tiles, `projector_state`, `overlap_state`, optional `Veff/support_tile` and `controller tokens` for panel ordering.
- Output: stream of `partial_HS_packets` that feed `Cluster B` via `A_to_B_partial_fifo`.
- Buffers:
  - `Psi_panel_ping` / `Psi_panel_pong`: double-buffered panel staging sized by `psi_panel_kib`.
  - `projector_state_bank` & `overlap_bank`: episode-resident banks keyed by basis metadata.
  - `partial_HS_fifo` + `a_partial_fifo_kib`: streaming buffer that matches `b_accum_buffer` arrival rate.

### 2.3 Configurable knobs for workload compatibility
- `panel_bands`, `row_block_size`: adjust fusion granularity so `FusedArrayEngine` matches workload band counts.
- `psi_panel_kib`, `projector_bank_kib`, `overlap_bank_kib`: size on-chip buffers to hold the largest panels and resident metadata.
- `a_array_lanes`, `a_fft_lanes`: set compute lanes per design point; `a_stream_lanes` controls the number of concurrent panel paths.
- `a_partial_fifo_kib` + `fifo_ab_kib`: tune emission bandwidth to keep `Cluster B` fed without overflowing on-chip bandwidth budget.

### 2.4 Likely bottlenecks
- Off-chip bandwidth into `PsiPanelReceiver` (governed by `offchip_bw_kib_per_us`) can starve the fused sweep if `Psi_panel` tiles exceed buffer depth.
- `ProjectorOverlapBank` lookup latency when multiple panels share projection data; misalignment would push more data back to host.
- `PartialEmitter` vs `B_accum_buffer`: insufficient `a_partial_fifo_kib` or `fifo_ab_kib` will throttle `Cluster B` and raise `stall_ratio_cluster`.

### 2.5 Cluster KPIs
- `T_A`: service time broken into `T_A_load`, `T_A_fft`, `T_A_array`, `T_A_emit`, capturing compute vs data movement balance.
- `A_to_B_emit_utilization`: ratio of actual packets emitted versus the observed A→B effective stream service rate / FIFO drain rate.
- `resident_fit` contribution from `projector_bank_kib`/`overlap_bank_kib` inside the `onchip_resident_budget_kib`.

## 3. Cluster B: subspace build implementation

### 3.1 Module tree
- `PartialAggregator`: fetches `partial_HS_packets` from `A_to_B_partial_fifo` and merges them into local accumulation lanes (dimensioned by `b_accum_lanes`).
- `LocalReducer`: reduction tree that collapses the accumulated partials into triangular `H_sub` / `S_sub` tiles while respecting hermitian symmetry and tiling by `row_block_size`.
- `MatrixStager`: writes reduced tiles into `H_sub_stage_buffer` and `S_sub_stage_buffer`, handling backpressure when `Cluster C` is busy.
- `DescriptorEmitter`: gathers pointers + metadata into `reduced_matrices_descriptor` objects and emits them through `B_to_C_reduced_fifo`.
- `AggregationMonitor`: tracks `reduction depth`, `emit readiness`, and triggers `residual_status` updates when partial streams lag.

### 3.2 Interfaces & buffers
- Inputs: `partial_HS_packets` from Cluster A, controller tokens for panel boundaries.
- Outputs: `reduced_matrices_descriptor` describing `H_sub` and `S_sub` staging addresses.
- Buffers:
  - `partial_HS_accum_buffer`: sized by `b_accum_buffer_kib` for interim accumulation.
  - `H_sub_stage_buffer` & `S_sub_stage_buffer`: hold reduced matrices until `Cluster C` claims them.
  - `B_to_C_reduced_fifo`: enforces barrier before `Cluster C`; size defined by `fifo_bc_kib`.

### 3.3 Configurable knobs for workload compatibility
- `b_accum_lanes` & `b_accum_buffer_kib`: scale accumulation throughput to match Cluster A emission.
- `b_reduced_stage_kib`: staging space for largest projected subspace matrices.
- `b_reduced_emit_bw_kib_per_us`: emission bandwidth knob that directly affects `T_B_emit`.
- `fifo_bc_kib`: ensures enough slack for `Cluster C` to absorb occasional spikes without backpressuring Cluster A.

### 3.4 Likely bottlenecks
- Reduction tree latency when `panel_bands` × `row_block_size` grows faster than `b_accum_lanes`, inflating `T_B_reduce`.
- Emission handshake with `Cluster C`: `B_to_C_reduced_fifo` must respect the barrier; insufficient depth forces `Cluster B` to stall even when local reduction completes.
- Resident footprint crossing `onchip_resident_budget_kib` once `H_sub_stage_buffer` grows, triggering spills and penalty `T_spill_penalty`.

### 3.5 Cluster KPIs
- `T_B`: tracked as `max(T_B_accum, T_B_reduce, T_B_emit)` to highlight accumulation vs emission tradeoffs.
- `Bytes_spill`: monitors spilled matrix bytes when `H_sub/S_sub` staging exceeds `onchip_resident_budget_kib`.
- `reduced_matrices_ready_ratio`: fraction of reduced descriptors emitted before controller sync, indicating how often `B→C` barrier becomes the critical path.

## 4. Interactions & controller expectations
- Persistent episode controller schedules `PsiPanelReceiver` panels, ensures `ProjectorOverlapBank` residency matches basis metadata, and gates `DescriptorEmitter` once `Cluster C` reports `diag_solution_descriptor` consumed.
- `A_to_B_partial_fifo`, `B_to_C_reduced_fifo`, and `C_to_D_solution_fifo` form the clustered backbone; sizes (`fifo_ab_kib`, `fifo_bc_kib`, `fifo_cd_kib`) should be tuned per workload to absorb `inner_steps` burstiness.
- Overlap rules from the freeze spec allow A and B to overlap their compute, but `B→C` must barrier, so `Cluster B` must track emission readiness to avoid wasted A cycles.

## 5. Summary of implementation-facing focus areas
- Keep `Psi_panel` double buffering, projector/overlap residency, and partial emission paths aligned with `resident_fit` budgets.
- Dimension `Cluster B` accumulators and staging buffers so that reduction latency stays lower than `T_A_emit` (to avoid back-pressure) while still enabling `Cluster C` to meet `T_C` targets.
- Track `T_A`, `T_B`, `Bytes_spill`, `resident_fit`, and `cdiaghg_mode_selected` per design point to align with the architecture model outputs and support later comparison against the shell contract metrics.

---
Modified file: `docs/architecture/qe_fpga_clustered_v1_cluster_ab_operator_build_spec_20260402.md`
