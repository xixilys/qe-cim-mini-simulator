# QE clustered v1 cycle-approx baseline rows（v0，2026-04-03）

## 1. 目的

这份文档给 `docs/architecture/qe_fpga_clustered_v1_architecture_model_template_v0.csv` 的第一版 baseline rows 提供口径说明。

它回答三个问题：

1. 哪些字段是 trace-backed
2. 哪些字段是 v0 architecture proxy
3. 哪些输出列已经由默认 proxy 公式填入，哪些仍然留空

## 2. 当前写入模板的 rows

当前已写入的 baseline rows 分两类：

### 2.1 主基线 rows

- `si4_pbe_uspp_small`
- `si8_pbe_uspp`
- `si8_pbe_nc`
- `graphene_pbe_uspp`
- `au_slab_subspace`
- `sic32_subspace`

### 2.2 辅助 stress row

- `bn32_pbe_uspp`

## 3. trace-backed 字段口径

下列字段优先来自 `bandsolver_trace.csv` 或已冻结 workload matrix：

- `npw`
- `nkb`
- `n_active`
- `m_expand`
- `panel_bands`

具体规则是：

- `npw / nkb / n_active / m_expand` 取对应 trace 中的最大值或冻结矩阵中的已确认值
- `graphene_pbe_uspp` 使用 trace 中的 `npw = 1133`，因此可能与先前摘要表中的 `1105` 存在轻微差异；当前以 trace 为准
- `inner_steps` 当前使用 `bandsolver_trace.csv` 中 `solver_iter` 的 rounded-mean proxy，而不是直接测得的硬件 inner-loop 计时

因此，`inner_steps` 在这一版 rows 中是：

- **trace-derived proxy**
- 不是 direct hardware timing

## 4. v0 architecture proxy 字段

下列字段在本轮属于 implementation-facing proxy，而不是实测：

- `row_block_size`
- `psi_panel_kib`
- `projector_bank_kib`
- `overlap_bank_kib`
- `a_stream_lanes`
- `a_fft_lanes`
- `a_array_lanes`
- `a_partial_fifo_kib`
- `b_accum_lanes`
- `b_accum_buffer_kib`
- `b_reduced_stage_kib`
- `c_reduced_dim_cap`
- `c_solver_parallelism`
- `c_input_buffer_kib`
- `c_eigvec_buffer_kib`
- `c_eigval_buffer_kib`
- `d_refresh_lanes`
- `d_refresh_buffer_kib`
- `d_pnext_slots_kib`
- `fifo_ab_kib / fifo_bc_kib / fifo_cd_kib`

这些值遵循三条规则：

1. 不能违反 `port_memory_freeze_v0`
2. 必须与 bucket/mode axis 兼容
3. 必须让 `resident_fit / bytes_spill_kib` 的结果可解释

## 5. 当前已填的派生列

当前模板已直接填入下面两类派生结果：

- `resident_fit`
- `bytes_spill_kib`

它们完全按 `architecture_model_v0` 的 resident / spill 公式计算，不需要额外猜测。

同时：

- 当 `resident_fit = yes` 时，当前 baseline row 先标记 `cdiaghg_mode_selected = hardware`
- 当 `resident_fit = no` 时，当前 baseline row 先标记 `cdiaghg_mode_selected = fallback_companion`

这只是 **v0 baseline gating result**，不是最终 crossover 结论。

## 6. 当前已填的 latency 列

当前模板已经按默认 proxy 公式填入：

- `t_a_us`
- `t_b_us`
- `t_c_us`
- `t_d_us`
- `t_episode_cluster_lb_us`

这些值来自：

- `docs/architecture/qe_fpga_clustered_v1_cycle_proxy_formula_contract_v0_20260403.md`

并且当前应被理解为：

- **default proxy value**
- 不是 direct measured hardware latency

## 7. 当前故意留空的输出列

下面这些列当前仍然留空：

- `crossover_margin_us`

原因是：

- `T_companion` 的 case-bound baseline 还没有合并进同一张参数表
- current rows 先完成 cluster-side episode latency，不冒充已经完成 hardware-vs-companion sweep

## 8. 如何使用这一版 rows

这版 rows 的用途是：

1. 作为下一步 batch sweep 的起点
2. 作为 HLS / cycle-approx 的 first configuration set
3. 先判断哪些 case 天然 resident-fit，哪些 case 天然触发 spill/fallback
4. 先判断 `T_A / T_B / T_C / T_D` 哪个 cluster 是默认主瓶颈

不应把这版 rows 直接当成：

- 已完成的 cycle-approx latency result
- 已完成的 FPGA speedup 结果
- 已完成的 `Cluster C` crossover sweep

## 9. 下一步建议

基于这版 rows，下一步最合理的是：

1. 讨论这些默认系数该怎样从 trace / HLS / board 数据反推
2. 把 `T_companion` 合并到同一张表
3. 对每个 row 做 `fifo_* / resident_fit / cdiaghg_mode_selected` sweep
4. 冻结第一版 `crossover_margin_us`
