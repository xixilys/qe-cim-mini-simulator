# QE shell-level 比较指标合同（v0，2026-04-02）

## 0. 目的

这份文档用于冻结 `Task 3` 的比较指标，确保后续：

- analytical model
- SystemC shell-level model
- CPU only baseline
- CPU + GPU baseline
- CPU + FPGA baseline

都使用同一套指标口径。

这份合同服务的系统对象是：

- `QE-connected band-solver subsystem`
- 不是完整 `DFT SoC`
- 也不是孤立 kernel benchmark

## 1. 总原则

### 1.1 比较必须是 shell-level，而不是 kernel-peak

核心比较对象固定为：

1. **primary object**：单次 `c_bands episode`
2. **secondary object**：单次 `SCF iteration`
3. **optional object**：完整 `SCF run` wall time

因此：

- 不能只报 `h_psi` 或 GEMM 的峰值吞吐；
- 不能拿理论 `GPU peak FLOPS` 直接作为比较对象；
- 必须把 host-device / host-accelerator / accelerator-memory 开销纳入同一统计口径。

### 1.2 指标分层

本合同把指标分为四层：

1. **workload descriptors**：描述 case 形状，不用于宣称赢；
2. **primary performance metrics**：直接决定是否加速；
3. **traffic and utilization metrics**：解释为什么赢或为什么输；
4. **energy metrics**：作为第二层目标，不先于性能结论。

### 1.3 所有 baseline 必须遵守相同 accounting 边界

对 `CPU only`、`CPU + GPU`、`CPU + FPGA` 三类 baseline，必须统一：

- 输入 case；
- 收敛阈值；
- shell 边界；
- 计入项和不计入项。

## 2. 必报 workload descriptor

这些量不是主要胜负指标，但必须和每个 case 一起上报。

| 字段 | 含义 | 单位 | 层级 |
| --- | --- | --- | --- |
| `npw` | plane-wave basis size | count | case |
| `nkb` | projector count | count | case |
| `max_subspace_n` | max retained basis size | count | case |
| `max_subspace_m` | max expansion block size | count | case |
| `fft_grid` | FFT grid dimensions | tuple | case |
| `dominant_solver` | dominant eigensolver family | enum | case |
| `generalized_ratio` | generalized path share | ratio | case |
| `scf_iters` | total SCF iterations | count | run |
| `cbands_calls` | `c_bands` calls | count | run |

## 3. Primary performance metrics

这些指标决定后续是否可以说“某设计点更优”。

### 3.1 `c_bands episode latency`

- **定义**：一次 `c_bands` episode 从 host 发起到结果返回完成的 wall-clock 或 modeled elapsed time。
- **单位**：`ms` 或 `s`
- **层级**：episode
- **强制性**：必须

这是第一主指标，因为当前系统对象就是 `QE-connected band-solver subsystem`。

### 3.2 `SCF iteration latency`

- **定义**：一次完整 `SCF iteration` 的 elapsed time，包括 `rho -> Veff`、`c_bands episode`、`psi -> rho_out` 以及必要的 shell-level软件交互。
- **单位**：`ms` 或 `s`
- **层级**：iteration
- **强制性**：必须

这是第二主指标，因为某个加速器即使加速了 `c_bands`，也可能在整个 `SCF iteration` 上收益有限。

### 3.3 `end-to-end wall time`

- **定义**：完整 run 从启动到收敛结束的总时间。
- **单位**：`s`
- **层级**：run
- **强制性**：建议，至少对主 workload matrix 中的核心 case 报告

### 3.4 `speedup`

必须至少报告两个 speedup：

- `speedup_episode = T_episode_baseline / T_episode_candidate`
- `speedup_scf_iter = T_scf_iter_baseline / T_scf_iter_candidate`

不得只报单 kernel speedup 作为系统 speedup 的替代品。

## 4. Traffic metrics

这些指标用来解释 memory wall 和边界开销。

### 4.1 `Host-device traffic`

- **定义**：host 与 GPU/FPGA 间的数据传输总量。
- **单位**：`bytes` / `KiB` / `MiB`
- **层级**：episode / iteration
- **强制性**：必须

对 `CPU only` 可以记为 `0`，但要保持字段存在。

### 4.2 `accelerator off-chip-memory traffic`

- **定义**：GPU global memory 或 FPGA off-chip memory 的读写流量。
- **单位**：`bytes`
- **层级**：stage / episode
- **强制性**：必须

对当前项目，特别要区分：

- Host ↔ FPGA
- FPGA on-chip ↔ off-chip memory

### 4.3 `resident hit / spill accounting`

- **定义**：对象是 resident、streamed 还是 spilled 的统计；以及 spill 次数/字节量。
- **单位**：count + bytes
- **层级**：episode
- **强制性**：建议，但对 FPGA 方案强烈建议

## 5. Utilization and stall metrics

这些指标决定“为什么没有赢”。

### 5.1 `stall ratio`

- **定义**：某 stage 或 engine 等待数据、等待 buffer、等待同步的时间占比。
- **单位**：ratio / %
- **层级**：stage / episode
- **强制性**：必须（对于 SystemC/model-based comparison）

### 5.2 `utilization`

- **定义**：某 engine 或 pipeline 处于 active state 的时间占比。
- **单位**：ratio / %
- **层级**：stage / engine / episode
- **强制性**：必须（对于 accelerator candidate）

### 5.3 `overlap efficiency`

- **定义**：理论可重叠部分与实际重叠成功部分的比例，或等价的“non-overlapped penalty”。
- **单位**：ratio / time
- **层级**：episode
- **强制性**：建议

## 6. Analytical-model metrics

这些指标服务于 `Task 4`，但定义必须现在先冻结。

| 指标 | 定义 | 单位 | 强制性 |
| --- | --- | --- | --- |
| `Ops` | stage arithmetic operation count | ops | 必须 |
| `Bytes` | stage total data movement count under the chosen accounting boundary | bytes | 必须 |
| `AI` | `Ops / Bytes` | ops/byte | 必须 |
| `T_compute_lb` | `Ops / PeakCompute` | time | 必须 |
| `T_bw_lb` | `Bytes / EffectiveBandwidth` | time | 必须 |
| `bound_type` | `compute-bound / bandwidth-bound / mixed` | enum | 必须 |

必要时可扩展：

- `T_onchip_lb`
- `T_host_sync_lb`
- `T_companion_lb`

## 7. Energy metrics

能耗是重要指标，但在当前阶段是 second-order objective。

### 7.1 `energy per episode`

- **定义**：一次 `c_bands episode` 的总能耗估计或实测值。
- **单位**：`J` / `mJ`
- **层级**：episode
- **强制性**：建议

### 7.2 `energy breakdown`

至少拆成：

- compute energy
- data movement energy
- idle / stall energy（如可得）

### 7.3 `energy-delay style composite`

如需综合评价，可选：

- `EDP`
- `ED^2P`

但不得用复合指标替代原始 latency 与 energy。

## 8. 计入项与不计入项

### 8.1 必须计入

以下开销必须计入 steady-state 系统比较：

- host-device transfer
- accelerator launch / dispatch overhead
- synchronization / completion wait
- layout transform / reformatting
- companion-solver path cost
- off-chip-memory traffic cost

### 8.2 不计入 steady-state core comparison

以下可不计入 steady-state 主性能指标，但要单独说明：

- FPGA bitstream generation
- RTL synthesis / P&R time
- one-time library compile/setup
- offline trace preprocessing

## 9. 推荐的最终汇报表

后续每个主 case 至少产出下面三张表。

### 9.1 Case descriptor table

| case | npw | nkb | subspace_n | subspace_m | fft_grid | solver |
| --- | ---: | ---: | ---: | ---: | --- | --- |

### 9.2 Primary comparison table

| case | baseline | episode latency | SCF iter latency | wall time | speedup_episode | speedup_iter |
| --- | --- | ---: | ---: | ---: | ---: | ---: |

### 9.3 Explanation table

| case | baseline | host-device traffic | off-chip traffic | stall ratio | utilization | energy/episode |
| --- | --- | ---: | ---: | ---: | ---: | ---: |

## 10. 冻结结论

`Task 3` 的冻结结论是：

- **不能只看 kernel FLOPs 或单 kernel latency**；
- **主比较对象固定为 `c_bands episode` 和 `SCF iteration`**；
- **流量、stall、utilization 与 energy 是解释性强制指标，不是可有可无的附录**；
- **所有 baseline 都必须在同一 shell 语义下比较，而不是和理论峰值比较**。

因此，后续 `Task 4` 的 analytical model 与 `Task 5` 的 SystemC model，都必须直接输出本合同里的指标，而不是另起一套口径。
