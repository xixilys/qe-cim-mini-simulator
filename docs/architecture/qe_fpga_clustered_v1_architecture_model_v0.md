# QE shell clustered FPGA v1 参数化架构模型（2026-04-02）

## 1. 作用

这份文档对应 `Task 12`。

它的职责不是继续扩写 `BODY_01/02/03/04` 的行为细节，而是把已经冻结的 clustered v1 架构转成一个**可扫参数、可比较、可落表**的 architecture-facing model。

它回答的是下面这些问题：

- cluster 级 latency 应该怎么算；
- 哪些参数决定 `CPU + FPGA` 的真实实现可行性；
- 哪些对象必须 resident，何时会 spill；
- hardware `cdiaghg` 与 fallback companion 的 crossover 应该怎么判断。

这份模型服务于：

- 后续 FPGA 设计空间探索；
- `CPU only / CPU + GPU / CPU + FPGA` 最终对比；
- 后续把 shell contract model 转到 implementation-facing 评估。

## 2. 模型范围

当前模型对象固定为：

> `QE-connected band-solver subsystem`

模型内部采用已经冻结的 v1 cluster 划分：

- Cluster A：fused `h_psi + s_psi`
- Cluster B：`build H_sub / S_sub`
- Cluster C：hardware `cdiaghg`
- Cluster D：`refresh / residual -> P_next`
- Episode Controller：persistent device-side scheduler

下列部分继续作为 shell-support path 处理，而不并入当前主内环模型：

- `rho -> Veff`
- `psi -> rho_out`
- `mix_rho`

## 3. 输出指标

每个 design point 至少输出以下结果：

- `T_A`, `T_B`, `T_C`, `T_D`
- `T_episode_cluster_lb`
- `Bytes_host_fpga`
- `Bytes_offchip`
- `Bytes_spill`
- `stall_ratio_cluster`
- `resident_fit`
- `cdiaghg_mode_selected`
- `crossover_margin`

这些指标最终要能对齐到 Task 6 的 shell-level comparison table。

## 4. 参数分组

### 4.1 Case parameters

这些来自 workload / QE trace：

- `npw`
- `nkb`
- `n_active`
- `m_expand`
- `fft_grid_points`
- `inner_steps`
- `dominant_solver`

这里要求把 **当前 trace-backed 实现包络** 与 **reserve-large 预留包络** 分开记录：

- 当前 baseline design-point 应直接来自当前 ready workload matrix
- `Au slab`、`SiC32` 一类 large case 若尚未冻结到同等粒度的 per-episode subspace summary，应在表中显式标为 reserve / conditional rows，而不是冒充当前 baseline row

### 4.2 Cluster A parameters

- `panel_bands`
- `row_block_size`
- `psi_panel_kib`
- `projector_bank_kib`
- `overlap_bank_kib`
- `a_stream_lanes`
- `a_fft_lanes`
- `a_array_lanes`
- `a_partial_fifo_kib`

### 4.3 Cluster B parameters

- `b_accum_lanes`
- `b_accum_buffer_kib`
- `b_reduced_stage_kib`
- `b_reduced_emit_bw_kib_per_us`

### 4.4 Cluster C parameters

- `c_reduced_dim_cap`
- `c_solver_parallelism`
- `c_input_buffer_kib`
- `c_eigvec_buffer_kib`
- `c_eigval_buffer_kib`
- `c_compute_us_per_n3`
- `c_emit_bw_kib_per_us`

### 4.5 Cluster D parameters

- `d_refresh_lanes`
- `d_refresh_buffer_kib`
- `d_pnext_slots_kib`
- `d_writeback_bw_kib_per_us`

### 4.6 System parameters

- `fifo_ab_kib`
- `fifo_bc_kib`
- `fifo_cd_kib`
- `onchip_resident_budget_kib`
- `offchip_bw_kib_per_us`
- `host_fpga_bw_kib_per_us`
- `controller_sync_us`
- `spill_penalty_us_per_kib`

### 4.7 Port / memory hierarchy baseline parameters

这些来自 `docs/architecture/qe_fpga_clustered_v1_port_memory_freeze_v0_20260403.md`：

- `host_desc_w_bits`
- `host_status_w_bits`
- `dma_data_w_bits`
- `dma_burst_bytes`
- `dma_align_bytes`
- `cluster_stream_w_bits`
- `controller_token_w_bits`
- `credit_ack_w_bits`
- `lutram_ctrl_budget_kib`
- `bram_stream_budget_kib`
- `uram_resident_budget_kib`

## 5. resident / spill 模型

### 5.1 Resident fit rule

定义：

`ResidentFootprint = projector_bank_kib + overlap_bank_kib + a_partial_fifo_kib + b_accum_buffer_kib + b_reduced_stage_kib + c_input_buffer_kib + c_eigvec_buffer_kib + c_eigval_buffer_kib + d_refresh_buffer_kib + d_pnext_slots_kib`

并冻结：

`onchip_resident_budget_kib = bram_stream_budget_kib + uram_resident_budget_kib`

判定：

- 若 `ResidentFootprint <= onchip_resident_budget_kib`，则 `resident_fit = yes`
- 否则 `resident_fit = no`

### 5.2 Spill bytes

若 `ResidentFootprint > onchip_resident_budget_kib`：

`Bytes_spill = ResidentFootprint - onchip_resident_budget_kib`

并增加：

`T_spill_penalty = Bytes_spill * spill_penalty_us_per_kib`

这个 penalty 是 architecture-facing proxy，不是最终 DMA 实测值。

Tier-0 `lutram_ctrl_budget_kib` 单独用于 controller / credit / status path，不并入 `ResidentFootprint`。

## 6. Cluster latency 模型

当前第一版 proxy 公式与默认系数冻结在：

- `docs/architecture/qe_fpga_clustered_v1_cycle_proxy_formula_contract_v0_20260403.md`

### 6.1 Cluster A

Cluster A 的核心不是单算子 latency，而是 fused operator sweep 的 steady-state service time。

取：

- `T_A_load`
- `T_A_fft`
- `T_A_array`
- `T_A_emit`

则：

`T_A = max(T_A_load, T_A_fft, T_A_array, T_A_emit)`

其中：

- `T_A_load` 受 `psi_panel_kib`、`projector_bank_kib`、`offchip_bw_kib_per_us` 影响
- `T_A_fft` 只在 support-grid / FFT path 打开时显著
- `T_A_array` 受 `a_array_lanes`、`panel_bands`、`row_block_size` 影响
- `T_A_emit` 受 `a_partial_fifo_kib` 与 A→B emission 带宽约束

当前 v0 默认 proxy 为：

- `T_A_load = psi_panel_kib / (offchip_bw_kib_per_us * k_dma_eff)`
- `T_A_fft = 0` if `a_fft_lanes == 0`, else `psi_panel_kib * k_a_fft_us_per_kib / a_fft_lanes`
- `T_A_array = (npw * panel_bands * projector_pressure) / (a_array_lanes * k_a_array_work_per_lane_per_us)`
- `T_A_emit = (a_partial_fifo_kib * projector_pressure) / (a_stream_lanes * k_ab_stream_eff)`

### 6.2 Cluster B

`T_B = max(T_B_accum, T_B_reduce, T_B_emit)`

其中：

- `T_B_accum`：局部 partial 聚合
- `T_B_reduce`：`H_sub / S_sub` 形成
- `T_B_emit`：B→C reduced descriptor 输出

当前 v0 默认 proxy 为：

- `T_B_accum = (b_accum_buffer_kib * projector_pressure) / (b_accum_lanes * k_b_accum_kib_per_lane_per_us)`
- `T_B_reduce = (b_reduced_stage_kib * subspace_pressure) / (b_accum_lanes * k_b_reduce_kib_per_lane_per_us)`
- `T_B_emit = b_reduced_stage_kib / (b_reduced_emit_bw_kib_per_us * k_bc_stream_eff)`

### 6.3 Cluster C

`T_C = max(T_C_input, T_C_compute, T_C_emit)`

其中：

- `T_C_input`：reduced descriptor 接收、`H_sub / S_sub` 装载、header 校验与 capacity check
- `T_C_compute`：hardware `cdiaghg` 纯计算，定义为 `T_C_factorize + T_C_transform + T_C_solver + T_C_backtransform`
- `T_C_emit`：`diag_solution_descriptor` 打包与输出

v0 里可用 proxy：

`T_C_compute ≈ c_compute_us_per_n3 * n_active^3 / c_solver_parallelism`

其中这个 cubic proxy 当前代表 `factorize + transform + solve + back-transform` 的合并近似，而不是某一个孤立子桶。

当前 v0 默认 proxy 展开为：

- `T_C_input = c_input_buffer_kib / (b_reduced_emit_bw_kib_per_us * k_bc_stream_eff)`
- `T_C_compute = (k_c_pipeline_factor * c_compute_us_per_n3 * n_active^3) / c_solver_parallelism`
- `T_C_emit = (c_eigvec_buffer_kib + c_eigval_buffer_kib) / (c_emit_bw_kib_per_us * k_cd_stream_eff)`

同时要求：

- `n_active <= c_reduced_dim_cap`

否则 hardware path 不可用，必须切 fallback。

`c_reduced_dim_cap` 的冻结口径是：

- 先稳定覆盖当前 trace-backed 基线包络（`graphene≈8`, `small-Si≈16`, `Si8≈32`）
- reserve-large case 通过 conditional rows 单独评估，不与当前 baseline-capacity 混写

### 6.4 Cluster D

`T_D = max(T_D_refresh, T_D_residual, T_D_writeback)`

其中：

- `T_D_refresh`：basis update
- `T_D_residual`：residual / precondition proxy
- `T_D_writeback`：`P_next` 写回到 resident slots

当前 v0 默认 proxy 为：

- `T_D_refresh = (d_pnext_slots_kib * subspace_pressure) / (d_refresh_lanes * k_d_refresh_kib_per_lane_per_us)`
- `T_D_residual = (d_refresh_buffer_kib + n_active / 4) / (d_refresh_lanes * k_d_residual_lane_eff)`
- `T_D_writeback = d_pnext_slots_kib / (d_writeback_bw_kib_per_us * k_cd_stream_eff)`

## 7. Episode latency 模型

### 7.1 内环 barrier 假设

当前 freeze 约束下：

- A 和 B 可以局部 overlap
- B→C 必须 barrier
- C→D 必须 barrier
- D→next-step 必须 barrier

因此 v0 episode latency 可写成：

`T_episode_cluster_lb = T_controller_setup + inner_steps * (max(T_A, T_B) + T_C + T_D + controller_sync_us) + T_spill_penalty`

这个公式比 body-based 统计更接近真实实现，因为它显式把 cluster 作为服务单元。

其中当前默认：

- `T_controller_setup = max(1, k_controller_setup_mul * controller_sync_us)`
- `T_spill_penalty = bytes_spill_kib * spill_penalty_us_per_kib`

### 7.2 Host-visible total

`T_episode_total = T_host_dispatch + T_episode_cluster_lb + T_host_completion`

这项将来需要对齐到 shell-level comparison table 中的 `c_bands episode latency`。

## 8. hardware cdiaghg vs fallback companion crossover

### 8.1 Fallback companion latency

定义：

`T_companion = T_pack_reduced + T_host_or_softcore_solve + T_return_solution + T_sync_back`

### 8.2 Hardware path latency

定义：

`T_hw_diag = T_C`

### 8.3 Crossover rule

若同时满足：

- `n_active <= c_reduced_dim_cap`
- `c_input_buffer_kib + c_eigvec_buffer_kib + c_eigval_buffer_kib <= available_diag_budget`
- `T_hw_diag + added_diag_buffer_penalty < T_companion`

则：

- `cdiaghg_mode_selected = hardware`

否则：

- `cdiaghg_mode_selected = fallback_companion`

并定义：

`crossover_margin = T_companion - (T_hw_diag + added_diag_buffer_penalty)`

这个量 > 0 时，说明硬件 `cdiaghg` 在当前 design point 下有系统收益空间。

## 9. 设计空间表头

后续每个 design point 至少记录：

- `case_id`
- `panel_bands`
- `row_block_size`
- `a_array_lanes`
- `b_accum_lanes`
- `c_reduced_dim_cap`
- `c_solver_parallelism`
- `d_refresh_lanes`
- `fifo_ab_kib`
- `fifo_bc_kib`
- `fifo_cd_kib`
- `onchip_resident_budget_kib`
- `resident_fit`
- `Bytes_spill`
- `T_A`
- `T_B`
- `T_C`
- `T_D`
- `T_episode_cluster_lb`
- `cdiaghg_mode_selected`
- `crossover_margin`

## 10. 当前 v0 直接结论

当前这份架构模型给出的最重要结论不是数值，而是判断顺序：

1. 先判断 resident fit，而不是先谈理论 FLOPs
2. 先判断 `hardware cdiaghg` 是否在 buffer/capacity 上可行
3. 再判断 `max(T_A, T_B) + T_C + T_D` 的主导项
4. 最后才进入 CPU/GPU/FPGA baseline compare

这比继续沿着 body 统计下钻，更接近真实 FPGA 实现决策。
