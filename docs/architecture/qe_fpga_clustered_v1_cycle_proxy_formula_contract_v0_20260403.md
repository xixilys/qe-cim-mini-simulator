# QE clustered v1 cycle-approx proxy 公式合同（v0，2026-04-03）

## 1. 目的

这份文档冻结第一版 `cycle-approx` 代理公式。

它的作用不是证明这些公式已经物理准确，而是先把下面三件事统一下来：

1. `T_A / T_B / T_C / T_D / T_episode_cluster_lb` 怎么算
2. 默认系数取什么值
3. 哪些列可以先写入 `architecture_model_template_v0.csv`

这份文档当前服务于：

- 第一版 architecture baseline rows
- 参数 sweep 的统一入口
- 后续讨论“这些默认值该怎么从 trace / board / HLS 中得到”

## 2. 使用边界

当前这套公式是：

- **implementation-facing proxy**
- **lower-bound-ish but conservative**
- **用于排序和 sensitivity，不用于宣称最终 FPGA 性能**

因此：

- 可以用来判断瓶颈转移
- 可以用来判断哪类 case 会先 spill / fallback
- 不能直接作为最终论文结果

## 3. 默认系数

### 3.1 通用效率系数

| 名称 | 默认值 | 作用 |
| --- | ---: | --- |
| `k_dma_eff` | `0.50` | off-chip bulk DMA 有效带宽折减 |
| `k_ab_stream_eff` | `0.75` | A→B stream 有效吞吐折减 |
| `k_bc_stream_eff` | `0.75` | B→C stream 有效吞吐折减 |
| `k_cd_stream_eff` | `0.75` | C→D / D writeback 有效吞吐折减 |
| `k_controller_setup_mul` | `8.0` | `controller_sync_us` 到 `T_controller_setup` 的放大系数 |

### 3.2 Cluster A 系数

| 名称 | 默认值 | 作用 |
| --- | ---: | --- |
| `k_a_fft_us_per_kib` | `0.10` | A 的 FFT side-path proxy |
| `k_a_array_work_per_lane_per_us` | `40.0` | A 的 array work proxy 吞吐 |

### 3.3 Cluster B 系数

| 名称 | 默认值 | 作用 |
| --- | ---: | --- |
| `k_b_accum_kib_per_lane_per_us` | `0.60` | B 的 local accumulation proxy 吞吐 |
| `k_b_reduce_kib_per_lane_per_us` | `1.00` | B 的 reduction proxy 吞吐 |

### 3.4 Cluster C 系数

| 名称 | 默认值 | 作用 |
| --- | ---: | --- |
| `k_c_pipeline_factor` | `2.0` | 用于把 `factorize + transform + solver + back-transform` 合并到 `T_C_compute` |

### 3.5 Cluster D 系数

| 名称 | 默认值 | 作用 |
| --- | ---: | --- |
| `k_d_refresh_kib_per_lane_per_us` | `0.75` | D 的 basis refresh proxy 吞吐 |
| `k_d_residual_lane_eff` | `1.50` | D 的 residual / precondition proxy 吞吐 |

## 4. 辅助压力项

定义：

- `projector_pressure = max(1, nkb / 64)`
- `subspace_pressure = max(1, n_active / 32)`

这两个量的作用是：

- `projector_pressure` 让 `USPP/PAW-heavy` case 在 A/B 上自然放大
- `subspace_pressure` 让大子空间 case 在 B/D 上自然放大

## 5. 公式

### 5.1 Cluster A

- `T_A_load = psi_panel_kib / (offchip_bw_kib_per_us * k_dma_eff)`
- `T_A_fft = 0` if `a_fft_lanes == 0`, else `psi_panel_kib * k_a_fft_us_per_kib / a_fft_lanes`
- `T_A_array = (npw * panel_bands * projector_pressure) / (a_array_lanes * k_a_array_work_per_lane_per_us)`
- `T_A_emit = (a_partial_fifo_kib * projector_pressure) / (a_stream_lanes * k_ab_stream_eff)`
- `T_A = max(T_A_load, T_A_fft, T_A_array, T_A_emit)`

### 5.2 Cluster B

- `T_B_accum = (b_accum_buffer_kib * projector_pressure) / (b_accum_lanes * k_b_accum_kib_per_lane_per_us)`
- `T_B_reduce = (b_reduced_stage_kib * subspace_pressure) / (b_accum_lanes * k_b_reduce_kib_per_lane_per_us)`
- `T_B_emit = b_reduced_stage_kib / (b_reduced_emit_bw_kib_per_us * k_bc_stream_eff)`
- `T_B = max(T_B_accum, T_B_reduce, T_B_emit)`

### 5.3 Cluster C

- `T_C_input = c_input_buffer_kib / (b_reduced_emit_bw_kib_per_us * k_bc_stream_eff)`
- `T_C_compute = (k_c_pipeline_factor * c_compute_us_per_n3 * n_active^3) / c_solver_parallelism`
- `T_C_emit = (c_eigvec_buffer_kib + c_eigval_buffer_kib) / (c_emit_bw_kib_per_us * k_cd_stream_eff)`
- `T_C = max(T_C_input, T_C_compute, T_C_emit)`

### 5.4 Cluster D

- `T_D_refresh = (d_pnext_slots_kib * subspace_pressure) / (d_refresh_lanes * k_d_refresh_kib_per_lane_per_us)`
- `T_D_residual = (d_refresh_buffer_kib + n_active / 4) / (d_refresh_lanes * k_d_residual_lane_eff)`
- `T_D_writeback = d_pnext_slots_kib / (d_writeback_bw_kib_per_us * k_cd_stream_eff)`
- `T_D = max(T_D_refresh, T_D_residual, T_D_writeback)`

### 5.5 Episode

- `T_controller_setup = max(1, k_controller_setup_mul * controller_sync_us)`
- `T_spill_penalty = bytes_spill_kib * spill_penalty_us_per_kib`
- `T_episode_cluster_lb = T_controller_setup + inner_steps * (max(T_A, T_B) + T_C + T_D + controller_sync_us) + T_spill_penalty`

## 6. 当前先不冻结的公式

下面这些当前仍然不在本合同里冻结：

- `T_companion`
- `crossover_margin_us`
- `T_host_dispatch`
- `T_host_completion`

原因是：

- host / companion 路径还没并入同一张 design-point 表
- companion solver 的默认 proxy 还没和 CPU baseline contract 对齐

## 7. 与模板的关系

当前 `architecture_model_template_v0.csv` 里已经可以直接填入：

- `t_a_us`
- `t_b_us`
- `t_c_us`
- `t_d_us`
- `t_episode_cluster_lb_us`

而 `crossover_margin_us` 当前仍可保持空列，直到 companion proxy 一起冻结。

对应的自动计算脚本是：

- `tools/benchmarks/compute_qe_clustered_cycle_proxy.py`

它会把本合同中的默认公式写回：

- `t_a_us`
- `t_b_us`
- `t_c_us`
- `t_d_us`
- `t_episode_cluster_lb_us`

## 8. 当前最值得质疑的默认项

下面这些默认系数目前最值得在后续讨论中优先替换：

- `k_dma_eff = 0.50`
- `k_a_array_work_per_lane_per_us = 40.0`
- `k_b_accum_kib_per_lane_per_us = 0.60`
- `k_b_reduce_kib_per_lane_per_us = 1.00`
- `k_c_pipeline_factor = 2.0`
- `k_d_refresh_kib_per_lane_per_us = 0.75`

原因不是它们一定错，而是它们当前：

- 还没有直接绑到 HLS schedule
- 还没有绑到板级 bandwidth 测试
- 还没有绑到具体 resource / frequency 约束

因此这些默认值当前只承担：

- 第一版排序
- 第一版 sensitivity
- 第一版 bottleneck 感知

不承担最终数值承诺。
