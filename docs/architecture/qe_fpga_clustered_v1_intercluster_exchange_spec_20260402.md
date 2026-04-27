# QE shell clustered FPGA v1 inter-cluster exchange specification (2026-04-02)

## 1. Scope

This implementation-facing spec constrains the data-exchange contracts between Cluster A/B/C/D and the persistent episode controller. It assumes the clustered partitioning and resident/spill bookkeeping described in the frozen architecture sheet, and focuses only on the inter-cluster packet formats, FIFO/credit/backpressure rules, resident/spill policy, bottlenecks, and pressure metrics for the small-Si, Si8, graphene, Au slab, and SiC32 workloads.

## 2. Packet assumptions

All clustered handoffs are word-aligned. The current v0 exchange model uses **128-bit lanes as the provisional default baseline width** for packet-size arithmetic and throughput estimates, but this is **not yet the frozen board-level interconnect contract**. Later port-freeze work may widen or narrow the datapath while preserving the packet/header semantics below. Unless otherwise noted, packets are delivered by cluster-local streaming fabrics and never drop; instead they stall senders via backpressure.

### 2.1 A→B: `partial_HS_packet`

- Payload: `phi(index,band,row_block)` partial accumulation plus 16‑byte header describing projector indices and row-block offsets.
- Width: `a_stream_lanes` lanes, each carrying 16 bytes per beat. One packet corresponds to a partial row-block sweep (prefetch size determined by `row_block_size`).
- Optional `has_overlap` flag toggles overlap reuse; set to true when Cluster A reuses overlap_state.
- Packets are emitted in row-major `psi_panel` order and tagged with `panel_serial` so B can correlate with reduction phases.

### 2.2 B→C: `reduced_matrices_descriptor`

- Payload: compressed `H_sub` and `S_sub` results (once per `panel_serial`) plus boundary metadata (`n_active`, `lanczos_step`, `spill_flag`).
- Descriptor includes `byte_count` to enforce `b_reduced_emit_bw_kib_per_us` when draining to C.
- Contains `resident_hint` bit that tells Cluster C whether input data is already resident (no read from offchip) or must be refetched.

### 2.3 C→D: `diag_solution_descriptor`

- Payload: `C` basis vectors (batched) and scalar `Lambda` pairs plus `residual_status` bits. Each descriptor carries `solution_span` (number of active columns) and `emit_mask` to signal partial emission when D consumes only a subset of vectors.
- `episode_continue_flag` is mirrored in the descriptor header so D can early terminate refresh writes if the episode is winding down.

### 2.4 D→Controller: `P_next_commit_descriptor`

- Payload: refreshed basis pointers, `delta_residual_norm`, `commit_mode`, and `spill_report` fields detailing which sub-blocks spilled due to resident overflow.
- `commit_mode` is frozen to three legal values:
  - `resident_commit`: default mode; `P_next` stays on-chip and becomes the next inner-step input without host visibility
  - `spill_commit`: controller schedules a spill to off-chip memory because resident budget overflowed
  - `host_export`: controller emits a host-visible descriptor only on episode exit, explicit debug/export, or a fallback boundary that requires software visibility
- Controller consumes this descriptor to update the persistent schedule and to drive the next `panel_serial` handed to Cluster A.

## 3. FIFO / credit / backpressure rules

- `fifo_ab`, `fifo_bc`, and `fifo_cd` are implemented as credit-based FIFOs whose depth in kibibytes is parametrized by `fifo_ab_kib`, `fifo_bc_kib`, and `fifo_cd_kib` respectively.
- Each producer obtains a credit ticket before emitting a packet. Tokens are retired when the downstream reader issues a dequeue acknowledgement after consuming the packet header. No data passes without an available credit, so upstream clusters stall automatically when the FIFO is saturated.
- Credits are returned via a separate `ctrl` channel to keep the data path purely streaming; credit return latency is accounted for in `controller_sync_us` because it gates the episode controller’s ability to pre-issue `panel_serial` tokens.
- Backpressure is signaled through the shared controller only when a FIFO stays above 90% occupancy for longer than `controller_sync_us`; in that case the episode controller pauses issuing new `panel_serial` values and defers the next `psi_panel_kib` load from Cluster A.
- Spilled packets (see Section 4) never re-enter the FIFO path; instead they are serialized to the off-chip buffer and reintroduced only after the resident footprint returns below `onchip_resident_budget_kib`.

## 4. Resident versus spill policy

- Resident footprint (`ResidentFootprint`) is monitored across all clusters using the formula from the architecture model (`projector_bank_kib`, `overlap_bank_kib`, etc.). When `ResidentFootprint <= onchip_resident_budget_kib`, all `partial_HS`, `H_sub/S_sub`, `diag_solution`, and `P_next` data stay on-chip and the controller keeps credits flowing without injecting spill markers. In this default case, `P_next` ends as `resident_commit`, not host export.
- If the footprint exceeds the budget, the controller marks `spill_flag` in the B→C descriptor and routes the excess bytes to the off-chip path. `Bytes_spill` is computed as `ResidentFootprint - onchip_resident_budget_kib`, and `T_spill_penalty` is added to the relevant cluster’s `T_X_emit` latency; this penalty should be treated as a lookup-based proxy (see `spill_penalty_us_per_kib`).
- Spill policy is prioritized as follows: `A` spills first (partially resetting `partial_HS_fifo`), then `B` (evicting accumulation buffers), and finally `C/D` (evicting eigenvector buffers). The controller tracks per-stage `spill_report` bits to avoid cascading saturation.

## 5. Exchange bottlenecks

- **A→B bottlenecks**: Determined by `a_partial_fifo_kib` and off-chip bandwidth; if `pipe_depth = FIFO_ab_depth` and `stall_ratio_ab` exceed 70%, the controller slows new `psi_panel` issuance and increases `Bytes_offchip` to keep the partials streaming. Small-Si and graphene cases tend to saturate this link because they emit dense partials for wide panels.
- **B→C bottlenecks**: Limited by `b_reduced_emit_bw_kib_per_us` and `c_input_buffer_kib`. When `n_active` approaches `c_reduced_dim_cap`, C cannot drain a new descriptor until B drops its FIFO depth, so `T_B_emit` increases sharply. Si8 and Au slab cases (large basis) should monitor `fifo_bc_peak` and `stall_ratio_bc` for signs of dithering.
- **C→D bottlenecks**: Driven by `c_emit_bw_kib_per_us` and `d_writeback_bw_kib_per_us`. If `diag_solution_descriptor` emission outruns D’s `refresh_lanes`, the controller must either throttle C’s `n_active` (enter fallback `cdiaghg_mode_selected = companion`) or accept higher `Bytes_spill`. SiC32, with tight refresh windows, is most sensitive to this limit.
- **Controller-mediated stalls**: When credit return delays stretch beyond `controller_sync_us`, the episode controller tapes `stall_ratio_cluster` increases across all clusters; this inflates `Bytes_offchip` directly and only inflates `Bytes_host_fpga` when the policy actually triggers `host_export` rather than `resident_commit`.

## 6. Metrics to judge exchange pressure

Every run across the target workloads (small-Si, Si8, graphene, Au slab, SiC32) must record the following per-cluster metrics so designers can judge whether FIFOs, credits, or resident budgets are the pressure points:

- `fifo_ab_peak_depth` / `fifo_bc_peak_depth` / `fifo_cd_peak_depth`
- `stall_ratio_ab` / `stall_ratio_bc` / `stall_ratio_cd`
- `credits_ab_inflight` / `credits_bc_inflight` / `credits_cd_inflight`
- `Bytes_spill` and `T_spill_penalty` contributions per cluster
- `Bytes_host_fpga` and `Bytes_offchip` per workload (to capture forced host transfers when exchange stalls)
- `resident_fit` flag and `ResidentFootprint` value
- `T_A_emit`, `T_B_emit`, `T_C_emit`, `T_D_writeback` to compare emit pressure
- `cdiaghg_mode_selected` and `crossover_margin` for workloads where hardware `cdiaghg` cannot keep pace (Si8, Au slab)

For trace comparison, annotate each metric with the workload label (`small-Si`, `Si8`, `graphene`, `Au_slab`, `SiC32`) and the `panel_serial` interval where pressure peaks. The goal is to produce a small table per workload that highlights which FIFO or resident threshold is hit first and whether spill bandwidth was sufficient to absorb the excess.

## 7. Reporting expectations

When reporting experimental results, always include the global `panel_serial` index window, the credit return latency (`controller_sync_us` measurement), and any enforced fallback mode. Attach the `spill_report` bits to the throughput summary so that hardware builders can correlate `Bytes_spill` spikes with the workloads named above.
