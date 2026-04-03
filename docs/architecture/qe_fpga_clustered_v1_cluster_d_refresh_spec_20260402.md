# Cluster D refresh / residual -> P_next module spec (2026-04-02)

## 1. Module tree

- **Episode Controller** (persistent scheduler)
  - manages inter-cluster handoffs, continuation flags, and status reporting
  - monitors `diag_solution_descriptor` from Cluster C and `P_next` writeback to resident slots
- **Cluster D Refresh Engine**
  - **Residual Precondition Block**: consumes `diag_solution_descriptor`, optionally reuses projector/overlap state, and computes residual/precondition metrics
  - **Basis Update Block**: applies refreshed coefficients to `P_next` slots, carrying loop-carried states such as basis indices and convergence flags
  - **Commit Arbiter**: drives `episode_continue_flag`, writes `P_next_descriptor`, and publishes `residual_status` to both the controller and Cluster A entry buffers

## 2. Update path overview

- **Input boundary**: `diag_solution_descriptor` (Cluster C output) must be fully visible before Cluster D begins work; barrier enforced (freeze spec §6.2).
- The Refresh Engine decomposes the descriptor into per-basis residuals, precondition scalars, and ortho-status signals used by the Basis Update Block.
- After refreshing, the Commit Arbiter writes `P_next_descriptor` into resident slots and updates `episode_status_register` so Cluster A and the controller can read the new basis for the next inner step.
- A continuation handshake writes `episode_continue_flag` into the controller and, when false, gates `P_next_slots` from being promoted to inner-loop residency.

## 3. Residual / precondition / orthogonalization / commit pipeline blocks

- **Residual Precondition Block**
  - Computes residual vectors and preconditioned corrections derived from `diag_solution_descriptor` plus any stored `residual_buffer` state (freeze spec §5.4).
  - Performs checks on convergence norms and orthogonality slack before forwarding data to the Basis Update Block.
  - Reports `residual_status` (converged / needs-more-iterations) both to the controller and to the Commit Arbiter, enabling gating of `episode_continue_flag`.
- **Basis Update Block**
  - Applies refresh operations over `d_refresh_lanes`, updating `P_next_slots` with the new basis and orthogonalized residuals (architecture model §4.5). Inputs come from `refresh_scratch_buffer` and `residual_buffer` to support staging.
  - Handles loop-carried state such as basis-slot indices, `P_next_descriptor` pointers, and historical precondition scalars so that each inner step reads the correct slot.
  - Emits orthogonality metrics (e.g., Gram-Schmidt dot products) to the Residual Precondition Block if re-orthogonalization is required in the next iteration.
- **Commit Arbiter**
  - Writes the refreshed basis to `P_next_descriptor` entry points and updates `episode_status_register` for Cluster A to use at the start of the next inner step.
  - Generates `episode_continue_flag` by combining `residual_status`, controller policy, and area/time KPIs.
  - Feeds back status words to Cluster C (if needed) in case the hardware diagonalizer needs to know whether the updated basis maintained required orthogonality.

## 4. Loop-carried state handling

- Loop-carried states include:
  - `P_next_slots` pointers and tags (which basis slot will be consumed by the next Cluster A sweep)
  - Residual/per-basis convergence scalars stored in `residual_buffer`
  - Episode continuation history inside `episode_status_register`
- The Residual Precondition Block keeps a read-modify-write window on `residual_buffer` so that precondition scalars survive barrier-enforced transitions (freeze spec §6.2).
- The Basis Update Block synchronizes its `d_refresh_lanes` across all `P_next_slots` guarded by the controller-provided `episode_continue_flag`, ensuring the next inner step only reads stable basis data (freeze spec §3.4).
- Commit updates are coordinated through the arbiter so that `episode_status_register` reflects the latest committed `P_next` before Cluster A re-reads the basis.

## 5. Buffers and bandwidth contracts

- `refresh_scratch_buffer` (Cluster D entry buffer)
  - Stages partials from Cluster C when `diag_solution_descriptor` is wide; must support `d_refresh_buffer_kib` capacity per architecture model §4.5.
  - Serves `d_refresh_lanes` at `d_writeback_bw_kib_per_us` when producing updates for `P_next_slots`.
- `residual_buffer`
  - Holds loop-carried residual/precondition entries between inner steps and exposes them to residual checks (freeze spec §5.4).
  - Must be sized so residual metrics do not spill; spills would force `resident_fit` failure (§5 resident/spill model). If spills occur, they incur `Bytes_spill` penalties in the architecture model (§5.2).
- `P_next_slots`
  - Resident basis storage for the refreshed `P_next`; double-buffering semantics are recommended so Cluster A can overlap reads (if allowed) with D’s writes, but the freeze spec mandates a barrier at `D -> next inner-step` (§6.2).
  - Should align with `d_pnext_slots_kib` parameter from architecture model §4.5.
- `episode_status_register`
  - Compact status word exposed to the controller capturing `residual_status`, `P_next_descriptor`, and `episode_continue_flag`.
  - Must be readable by both the Episode Controller and Cluster A to maintain consistent inner-loop state.

## 6. KPIs and compatibility parameters

- KPIs to track:
  - `T_D_refresh`, `T_D_residual`, `T_D_writeback` (latency contributions in architecture model §6.4).
  - `Bytes_spill` and `resident_fit` to ensure D’s buffers remain on-chip (Task 12 architecture model §5).
  - `episode_continue_flag` vs. `residual_status` mismatch rate (controls when hardware vs. software fallback is triggered).
  - `d_writeback_bw_kib_per_us` utilization and `d_refresh_lanes` occupancy (to expose streaming bottlenecks).
- Compatibility parameters (from architecture model §4.5):
  - `d_refresh_lanes`: the degree of parallel refresh lanes available; influences `T_D_refresh` and pipeline depth.
  - `d_refresh_buffer_kib`: sizing for the scratch buffer; must align with `refresh_scratch_buffer` capacity.
  - `d_pnext_slots_kib`: budget for resident basis slots; must be sufficient to store full `P_next` and avoid spill penalties.
  - `d_writeback_bw_kib_per_us`: throttle for writes back to resident storage; should be matched with controller scheduling to avoid backpressure.
  - `episode_status_register` width (implied) to encode `residual_status` health, continue flag, and commit pointers.

## 7. Likely bottlenecks and mitigation

- `diag_solution_descriptor` fan-in: If Cluster C emits wide descriptors faster than D can consume due to limited `d_refresh_lanes`, the `refresh_scratch_buffer` will fill and stall C→D FIFO; consider matching `c_emit_bw_kib_per_us` to D’s writeback bandwidth (§5.4 contract). If mismatched, either insert additional `C_to_D_solution_fifo` buffering or throttle C’s emission.
- Residual buffer spills: Under-resourced `residual_buffer` or insufficient `d_pnext_slots_kib` will force extra host-side transfers and penalize `resident_fit`; sizing must obey the architecture model’s resident footprint budgets (§5.1).
- Orthogonality feedback: The Residual Precondition Block must keep orthogonality checks light; otherwise `T_D_residual` can dominate latencies and degrade `T_episode_cluster_lb` (architecture model §7.1). Keep dot-product loops tightly pipelined and aligned with `d_refresh_lanes`.
- Episode continue flag synchrony: If the controller cannot observe `episode_status_register` before Cluster A re-enters, `P_next_slots` may be read stale; implement strong barrier semantics and status handshakes (freeze spec §6.2) to ensure D’s commit wins before next inner step.

## 8. Compatibility with healthy fallback

- When hardware `cdiaghg` falls back to companion, `diag_solution_descriptor` may contain host-originated descriptors; Cluster D must accept either hardware or host descriptors while still honoring the same `episode_continue_flag` semantics and buffer contracts.
- The Episode Controller should be aware of the fallback mode so that `episode_status_register` includes a `fallback` bit; D’s commit logic must only emit `P_next_descriptor` and `residual_status` once the fallback handshake is clear.

End of file.
