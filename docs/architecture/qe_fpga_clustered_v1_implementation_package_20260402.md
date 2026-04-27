# QE clustered v1 实现设计包总纲（2026-04-02）

## 1. 作用

这份文档是当前 clustered v1 进入 implementation-facing 设计阶段的总纲。

它不替代各个 cluster 的细化文档，而是负责固定三件事：

1. 模块级设计包的组织方式；
2. cluster 之间必须统一的接口与评价口径；
3. compatibility-first 的实现原则。

## 2. 当前设计包的组成

当前设计包现在由下面 11 个文档组成：

1. `docs/architecture/qe_fpga_clustered_v1_cluster_ab_operator_build_spec_20260402.md`
2. `docs/architecture/qe_fpga_clustered_v1_cluster_c_cdiaghg_spec_20260402.md`
3. `docs/architecture/qe_fpga_clustered_v1_cluster_d_refresh_spec_20260402.md`
4. `docs/architecture/qe_fpga_clustered_v1_intercluster_exchange_spec_20260402.md`
5. `docs/architecture/qe_fpga_clustered_v1_module_realization_outline_20260402.md`
6. `docs/architecture/qe_fpga_clustered_v1_module_interface_table_20260402.md`
7. `docs/architecture/qe_fpga_clustered_v1_buffer_memory_budget_table_20260402.md`
8. `docs/architecture/qe_fpga_clustered_v1_workload_bucket_mapping_20260402.md`
9. `docs/architecture/qe_fpga_clustered_v1_port_memory_freeze_v0_20260403.md`
10. `docs/architecture/qe_fpga_clustered_v1_cycle_approx_baseline_rows_v0_20260403.md`
11. `docs/architecture/qe_fpga_clustered_v1_cycle_proxy_formula_contract_v0_20260403.md`

本文件是它们之上的总纲。

## 3. 一个必须明确的边界

当前实现设计对象是：

> `c_bands` 主路径的 `CPU + FPGA` 设计

不是：

- `CPU only` 的设计
- 整个 `electrons()` 的 fully hardened design
- 完整 `SCF shell` 的 fully hardened design

因此：

- `CPU only` 只承担 baseline / reference 角色；
- 真正需要做模块级实现规格的只有 `CPU + FPGA`；
- `sum_band / v_of_rho / newd / mix_rho` 当前是 phase-2 扩展候选，不是 v1 主设计对象。

## 4. 统一接口合同

所有 cluster 文档必须共享下面 4 类接口字段。

### 4.1 Episode ingress fields

- `case_id`
- `npw`
- `nkb`
- `subspace_n`
- `subspace_m`
- `fft_grid`
- `projector_mode`
- `solver_mode`
- `precision_mode`

### 4.2 A→B partial contract

- `partial_type = H | S | HS_fused`
- `tile_id`
- `panel_id`
- `row_block_id`
- `payload_shape`
- `payload_bytes`
- `accum_policy`

### 4.3 B→C reduced contract

- `reduced_dim_n`
- `expand_dim_m`
- `matrix_layout`
- `hermitian_flag`
- `generalized_flag`
- `payload_bytes`

### 4.4 C→D solution contract

- `diag_dim_n`
- `eigenpair_count`
- `residual_visibility_mode`
- `solution_bytes`
- `fallback_flag`

## 5. 统一 KPI 合同

所有 cluster 文档必须至少报告三层指标：

### 5.1 Functional KPIs

- `supported_workload_bucket`
- `supported_mode`
- `fallback_condition`

### 5.2 Throughput / latency KPIs

- `service_time_per_episode_unit`
- `service_time_per_panel_or_tile`
- `throughput`
- `occupancy`
- `stall_ratio`

### 5.3 Memory / exchange KPIs

- `resident_footprint_kib`
- `buffer_footprint_kib`
- `spill_bytes_kib`
- `ingress_bytes`
- `egress_bytes`
- `backpressure_source`

## 6. compatibility-first 设计原则

### 6.1 不追求“一核通吃”

当前兼容性策略固定为：

- descriptor-driven execution
- bucketed datapath
- bounded fallback

### 6.2 兼容性通过参数和模式完成

至少要支持：

- `small-Si`
- `Si8`
- `graphene`
- `Au slab`
- `SiC32`

而不是为每个 case 做独立硬件。

### 6.3 最少应定义 3 个 workload buckets

- `small`
- `medium`
- `large`

并至少定义 2 个 projector modes：

- `NC-light`
- `USPP/PAW-heavy`

## 7. 交换瓶颈必须怎么审

当前任何 cluster 设计都不能只报“算得快”。

必须同时回答：

1. 输入从哪里来；
2. 输出往哪里去；
3. 哪个 FIFO 会先堵；
4. resident 不够时哪里会 spill；
5. 这个 bottleneck 是 compute-bound 还是 exchange-bound。

## 8. 三张统一表已经补齐

当前总包已经补齐下面 3 张实现级统一表：

1. **Module Interface Table**
   - `docs/architecture/qe_fpga_clustered_v1_module_interface_table_20260402.md`
2. **Buffer / Memory Budget Table**
   - `docs/architecture/qe_fpga_clustered_v1_buffer_memory_budget_table_20260402.md`
3. **Workload Bucket Mapping Table**
   - `docs/architecture/qe_fpga_clustered_v1_workload_bucket_mapping_20260402.md`

它们分别固定：

- 模块边界、信号输入输出、局部状态和 backpressure 来源；
- resident 对象、cluster buffer、FIFO 深度、spill 顺序和最少采集指标；
- workload bucket、模式轴、case 到 cluster 压力的映射，以及参数区间建议。

因此，当前 clustered v1 已经不再只有 cluster 命名，而是具备：

- cluster spec；
- inter-cluster exchange contract；
- module interface table；
- buffer / memory budget table；
- workload compatibility mapping。

这使得后续 RTL / HLS / cycle-approx 细化可以围绕统一合同展开，而不是继续停留在抽象 body 视角。

本轮跨文档一致性修正另行汇总在：

- `docs/architecture/qe_fpga_clustered_v1_consistency_fixlist_20260402.md`

后续若再修改 bucket、`Cluster C` latency 定义、`P_next` 边界语义、interconnect 位宽口径或 Cluster A KPI，必须同步更新这份 fixlist。

当前第二优先级的端口与 memory hierarchy baseline freeze 统一收在：

- `docs/architecture/qe_fpga_clustered_v1_port_memory_freeze_v0_20260403.md`

当前第三优先级的第一版 cycle-approx baseline rows 说明统一收在：

- `docs/architecture/qe_fpga_clustered_v1_cycle_approx_baseline_rows_v0_20260403.md`

当前第三优先级使用的默认 proxy 公式与系数统一收在：

- `docs/architecture/qe_fpga_clustered_v1_cycle_proxy_formula_contract_v0_20260403.md`

## 9. 当前冻结的瓶颈审查口径

当前每个 cluster 的第一优先瓶颈和必须采集的指标，冻结为下面这张总表：

| 域 / cluster | 主要输入 | 主要输出 | 先审的第一瓶颈 | 必采 KPI | 最敏感 workload |
| --- | --- | --- | --- | --- | --- |
| Episode Control / FIFO fabric | credit return, `spill_report`, `P_next_descriptor` | `panel_serial`, cluster gate, fallback select | `controller_sync_us` 过大导致全局 credit 回收变慢 | `fifo_ab_peak_depth`, `fifo_bc_peak_depth`, `fifo_cd_peak_depth`, `credits_*_inflight`, `resident_fit`, `Bytes_offchip` | 全部，尤其 `graphene_pbe_uspp` 与 `si8_pbe_nc` |
| Cluster A | `Psi_panel`, projector, overlap | `partial_HS_packet` | `offchip_bw_kib_per_us` 或 `fifo_ab_kib` | `T_A_load`, `T_A_array`, `T_A_emit`, `stall_ratio_ab`, `Bytes_host_fpga`, `Bytes_spill` | `si4_pbe_uspp_small`, `si8_pbe_nc`, `graphene_pbe_uspp` |
| Cluster B | `partial_HS_packet` | `reduced_matrices_descriptor` | `b_reduced_stage_kib` 不足或 `fifo_bc_kib` 太浅 | `T_B_accum`, `T_B_reduce`, `T_B_emit`, `stall_ratio_bc`, `reduced_matrices_ready_ratio`, `Bytes_spill` | `si8_pbe_uspp`, `au_slab_subspace`, `sic32_subspace` |
| Cluster C | `H_sub`, `S_sub` | `diag_solution_descriptor` | `c_input_buffer_kib` / `c_reduced_dim_cap` / `c_emit_bw_kib_per_us` | `T_C_input`, `T_C_compute`, `T_C_emit`, `cdiaghg_mode_selected`, `crossover_margin`, `resident_fit` | `au_slab_subspace`, `sic32_subspace`, `graphene_pbe_uspp` |
| Cluster D | `diag_solution_descriptor` | `P_next_descriptor`, `episode_continue_flag` | `d_writeback_bw_kib_per_us` 或 `d_refresh_lanes` 与 C 不匹配 | `T_D_refresh`, `T_D_residual`, `T_D_writeback`, `stall_ratio_cd`, `episode_continue_flag`, `Bytes_spill` | `graphene_pbe_uspp`, `au_slab_subspace`, `sic32_subspace` |

这张表的作用不是替代细化文档，而是固定：

1. 每个 cluster 最先应该盯哪一个 choke point；
2. 每个 cluster 必须交出哪些计算指标；
3. 后续 cycle model / RTL bring-up 时，哪些 workload 应该优先用来打压该 cluster。

## 10. 当前冻结的 workload 兼容策略

当前 compatibility-first 策略不再是“单 case 调一套参数”，而是冻结为：

- 三档 size bucket：`small` / `medium` / `large`
- 两档模式轴：`NC-light` / `USPP/PAW-heavy`
- 一套共享硬件，靠 descriptor 和参数表切换，而不是 per-case 重写 datapath

当前推荐的映射是：

| case | size bucket | mode axis | 主要价值 |
| --- | --- | --- | --- |
| `si4_pbe_uspp_small` | `small` | `USPP/PAW-heavy` | 小尺度半导体 bring-up，重点压 A→B |
| `si8_pbe_uspp` | `medium` | `USPP/PAW-heavy` | bulk Si 主 case，重点压 B→C |
| `si8_pbe_nc` | `medium` | `NC-light` | bulk Si 的 NC-light 补充 case，重点看 A 与 controller |
| `graphene_pbe_uspp` | `small` | `NC-light-like` | 高频 episode / 高频握手，重点看 controller 与 D |
| `au_slab_subspace` | `large` | `USPP/PAW-heavy` | interface/contact 主 case，重点压 C→D |
| `sic32_subspace` | `large` | `NC-light` | wide-bandgap 主 case，重点压 B/C/D 全链路 |

若还需要一个 projector-heavy 的附加压力 case，则保留 `bn32_pbe_uspp` 作为 secondary stress，而不是替换上面的器件主矩阵。

## 11. implementation-ready 的当前边界

到这一步，可以说 clustered v1 已经进入 **implementation-facing architecture package**，但还不能说已经进入 **implementation-ready FPGA design**。

当前还缺的不是“再讨论切分”，而是下面这些板级实现参数：

- interconnect 端口宽度与仲裁规则
- BRAM / URAM / HBM 的精确预算
- cluster 时钟目标与跨域策略
- `cdiaghg` 硬件 bucket 的具体数值算法冻结
- cycle-approx latency model 与后续 RTL / HLS 原型

也就是说，下一步工作应从“是否这样切”转向“这套切法怎样做成板上可实现的模块和时序约束”。
